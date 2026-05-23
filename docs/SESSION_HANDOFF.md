# SESSION HANDOFF — NameForge 2.0 (Odoo PIM)

Документ для старта **новой сессии ИИ / разработчика**. Legacy Streamlit + МойСклад — см. `docs/HANDOFF.md`.

---

## 1. Стек и среда

| Слой | Технологии | Где |
|------|------------|-----|
| **ERP** | Odoo **19.0 Community** (stable), VPS `https://erp.arszap.ru`, БД `stable_arszap` | Production-каталог |
| **Backend** | **FastAPI**, SQLAlchemy 2.0, Pydantic v2, `requests` → JSON-RPC | `backend/` |
| **Frontend** | **React 19**, **Vite**, **Tailwind**, shadcn/ui, **TanStack Query** + **TanStack Table** | `frontend/` |
| **Локальная БД** | SQLite `data/autoname.db` (`DATABASE_URL` в `.env`) | NameForge — источник истины для fitment, шаблонов, `source_hash` |
| **Разработка** | Локально на ноутбуке; деплой 2.0 на VPS — позже | — |

**Odoo API:** выделенный пользователь, `ODOO_UID` + API key / password. Протокол — **только** `POST {ODOO_URL}/jsonrpc` → `execute_kw`. См. `odoo_api_knowledge.md`, клиент: `backend/app/services/odoo_client.py`.

**Запуск (локально):**
```bash
# Backend
cd backend && uvicorn main:app --reload --port 8000

# Frontend (proxy /api → :8000)
cd frontend && npm run dev   # http://localhost:5173
```

**Маршруты SPA:**
- `/` — **Главный дашборд** (KPI + Quick Actions)
- `/catalog` — Data Grid каталога
- `/categories`, `/templates` — настройка категорий и шаблонов

**Путь к БД:** `DATABASE_URL` резолвится в **абсолютный** путь от корня проекта (`backend/app/core/config.py`), чтобы uvicorn из `backend/` не создавал пустую БД в `backend/data/`. При первом старте создаются Odoo cache-таблицы, `product_fitments` и additive patches (`schema_patches`).

---

## 2. Текущий статус API и БД

### 2.1 ETL-пайплайн каталога (CLI + API Jobs) — DONE

Полный контур **Extract → Transform → Load → Push** реализован через CLI-скрипты **и** UI-триггеры. Все write-path в Odoo — только через `SyncService`.

| Шаг | CLI | API (UI) | Сервис |
|-----|-----|----------|--------|
| **Extract (Odoo → local)** | `scripts/sync_catalog_from_odoo.py` | `POST /api/jobs/sync-from-odoo` → `202` | `product_catalog_sync.sync_products_from_odoo()` |
| **Transform (JSONL → local)** | `scripts/enrich_catalog_from_jsonl.py --apply` | `POST /api/jobs/enrich` → `202` | `catalog_jsonl_enrichment.run_catalog_jsonl_enrichment()` |
| **Load (Push local → Odoo)** | `scripts/mass_sync_to_odoo.py [--force-apply]` | `POST /api/jobs/push-to-odoo` → `202` | `mass_sync_job.run_mass_sync_to_odoo()` → `SyncService` |

**Background Jobs (`backend/app/api/routers/jobs.py`):**
- Немедленный ответ **`202 Accepted`**; работа в `BackgroundTasks` FastAPI.
- Каждый runner создаёт **собственный** `SessionLocal()` (изоляция от request-session).
- **In-memory mutex** (`job_lock.py`): повторный запуск того же job → **`409 Conflict`** (`Job is already running`).
- Логика вынесена в сервисы (`job_tasks.py`, `catalog_jsonl_enrichment.py`, `mass_sync_job.py`); CLI переиспользует те же функции.

**Рекомендуемый порядок полного цикла (CLI):**
```bash
python scripts/sync_odoo_categories.py
python scripts/sync_catalog_from_odoo.py
python scripts/enrich_catalog_from_jsonl.py --apply
python scripts/mass_sync_to_odoo.py               # DRY_RUN симуляция
python scripts/mass_sync_to_odoo.py --force-apply # live → erp.arszap.ru
```

### 2.2 Главный дашборд — DONE

| Компонент | Назначение |
|-----------|------------|
| **`GET /api/metrics/dashboard`** | SQL-агрегаты KPI: `total_products`, `synced`, `pending`, `locked` (только локальный кэш, без Odoo HTTP) |
| **`MainDashboard.tsx`** | 4 KPI-карточки; TanStack Query `refetchInterval` ~45 с |
| **Quick Actions** | Кнопки «Скачать из Odoo», «Обогатить из JSONL», «Массовая отправка» → `POST /api/jobs/*` + Sonner toast |

### 2.3 Data Grid: серверная фильтрация и ошибки sync — DONE

**`GET /api/products`** — опциональные query-параметры (применяются в SQL **до** `limit`/`offset`):

| Параметр | Назначение |
|----------|------------|
| `search` | Case-insensitive `LIKE` по `article`, `external_code`, `generated_name`, кэшированному Odoo-имени |
| `naming_status` | `no_template` / `pending_sync` / `synced` (SQL-аппроксимация) |
| `is_locked` | Фильтр по `name_locked` |
| `has_error` | Только строки с заполненным `last_sync_error` |

**Поле `products.last_sync_error`** (nullable, patch в `schema_patches.py`):
- `SyncService` записывает текст ошибки при сбое JSON-RPC / commit; очищает при успешном push.
- UI: иконка `AlertTriangle` + Tooltip в колонке превью (`CatalogTable.tsx`).

**Frontend Toolbar:** debounce-поиск **400 мс**, Select-фильтры, `keepPreviousData`, сброс `pageIndex` при смене фильтров.

**Реализация:** `backend/app/services/catalog_query.py`, `backend/app/api/catalog.py`.

### 2.4 Manual Override (Human-in-the-loop) — DONE

**Бизнес-смысл `name_locked` (уточнён):**

| Контекст | Поведение |
|----------|-----------|
| **Enrich / Webhooks / batch generate / fitment persist** | TemplateEngine **не перезаписывает** `generated_name` (`persist_generation_result`, `apply_product_text_fitment`) |
| **SyncService / mass push / batch sync** | Locked-товар **может и должен** уходить в Odoo, если изменился `source_hash` (ручная правка оператора). Preview **не** вызывается — берётся stored `generated_name`. |
| **`sync_queue.py`** | Locked-товары **включены** в кандидаты при `synced_at IS NULL` или `generation_status = 'review'` |

**API:** `PATCH /api/products/{product_id}/override`
- Payload: `{ manual_name?: str, is_locked?: bool }`
- При lock + `manual_name` → запись в `generated_name`, пересчёт `source_hash` (`compute_sync_content_hash`), `generation_status = 'review'`, `last_sync_error = NULL`.

**UI:** `FitmentEditorSheet.tsx` переименован по смыслу в **«Карточка товара»** — Switch «Ручная фиксация имени (Lock)», Input для ручного имени, optimistic update TanStack Query.

**Сервисы:** `product_override_service.py`, `backend/app/api/product_override.py`.

### 2.5 Локальный кэш и fitment — DONE

| Таблица / поле | Назначение |
|----------------|------------|
| **`products`** | PIM-кэш: `generated_name`, `search_keywords`, `source_hash`, `synced_at`, **`last_sync_error`**, `name_locked`, denormalized fitment |
| **`fitments`**, **`product_fitments`** | Текстовая и directory-применимость для UI |
| **`odoo_categories`** | 216 категорий; 56 с `name_pattern` |

**Fitment API:**
- `GET /api/vehicles/makes|models|generations` — mock (`vehicle_directory.py`)
- `POST /api/products/{product_id}/fitment` — save IDs + regenerate preview (если не locked)

### 2.6 Прочее (без изменений в этой волне)

- **`POST /api/odoo/sync/categories`**, Template Builder (`/templates`), webhooks (`POST /api/webhooks/odoo/product`).
- **`POST /api/sync/odoo`** — batch push выбранных ID через `SyncService`.
- **`POST /api/products/batch/generate-name`** — пакетная генерация (skip locked).

---

## 3. Golden Rules (не ломать)

1. **Только JSON-RPC** — `execute_kw` через `OdooClient`. **XML-RPC под абсолютным запретом.** Запрещены cookie-сессии, `authenticate`, `/web/session/authenticate`.
2. **Запись в Odoo ТОЛЬКО через `SyncService`** — push (`POST /api/sync/odoo`, webhooks, `mass_sync_to_odoo.py`, `POST /api/jobs/push-to-odoo`) делегирует в `SyncService.sync_products()`. Прямые `client.write()` вне сервиса — **запрещены**.
3. **Идемпотентность (`source_hash`)** — перед `write` сравнивать hash; skip только при **неизменном** hash **и** наличии `synced_at`. Изменение hash (в т.ч. после manual override) → товар снова eligible для push.
4. **`name_locked` — двойная семантика:**
   - **Блокирует автогенерацию** (TemplateEngine / enrich / webhook persist / fitment persist).
   - **НЕ блокирует Odoo sync** — ручное имя в `generated_name` отправляется через `SyncService` по тем же правилам `source_hash`.
5. **`DRY_RUN=true` (default)** — симуляция без HTTP write. Live: `DRY_RUN=false` в `.env` **или** `--force-apply` в CLI.
6. **`x_search_keywords`** — обязательное поле при push вместе с `name`.
7. **Генерация имён — pure function** — `generate_naming_result()` без I/O; I/O на границах API/sync/CLI/jobs.
8. **Без hardcoded UUID** — ID из Odoo cache или env.
9. **Код EN / UI RU** — комментарии на английском, UI-строки на русском.
10. **Background jobs** — один экземпляр job-типа за раз (in-memory mutex; при масштабировании на несколько воркеров потребуется Redis/DB lock).

---

## 4. Ключевые файлы

| Область | Путь |
|---------|------|
| **Dashboard KPI** | `backend/app/api/routers/metrics.py`, `services/metrics_service.py`, `frontend/.../MainDashboard.tsx` |
| **Background jobs** | `backend/app/api/routers/jobs.py`, `services/job_tasks.py`, `job_lock.py` |
| **Catalog filters** | `backend/app/services/catalog_query.py`, `frontend/.../CatalogTable.tsx` |
| **Manual override** | `backend/app/api/product_override.py`, `services/product_override_service.py`, `FitmentEditorSheet.tsx` |
| **Sync errors** | `products.last_sync_error`, `sync_service.py` |
| **ETL services** | `product_catalog_sync.py`, `catalog_jsonl_enrichment.py`, `mass_sync_job.py`, `sync_queue.py` |
| **Sync (write gate)** | `sync_service.py`, `api/sync.py` |
| **Fitment** | `fitment.py`, `fitment_service.py`, `HierarchicalFitmentSelect.tsx` |
| **Naming engine** | `template_service.py` (`compute_sync_content_hash`, `persist_generation_result`) |
| **Data Grid API client** | `frontend/src/lib/catalog-api.ts`, `metrics-api.ts`, `jobs-api.ts` |
| **DB patches** | `backend/app/core/schema_patches.py` |
| **Tests (новые)** | `test_dashboard_metrics.py`, `test_jobs_api.py`, `test_catalog_filters.py`, `test_product_override.py`, `test_sync_queue.py` |

---

## 5. Проверки качества (baseline)

```bash
ruff check .
pytest                    # 146+ tests green
cd frontend && npm run build
```

---

## 6. Следующая цель — Live Job Progress (New Focus)

**Задача:** мониторинг **прогресса выполнения фоновых ETL-задач** в UI дашборда (сейчас jobs fire-and-forget: `202` + toast, без статуса выполнения).

**Ожидаемый scope (черновик):**
- Backend: job state store (in-memory → позже SQLite/Redis): `status`, `started_at`, `finished_at`, `progress` (processed/total), `error`, `stats`.
- `GET /api/jobs/status` или SSE/WebSocket для live updates.
- UI на Main Dashboard: индикатор «идёт импорт / enrich / push», progress bar, последний результат; блокировка повторного запуска уже есть (`409`).
- Не ломать mutex и изолированные DB-сессии в runners.

**Не начинать без:** выбора transport (polling vs SSE) и решения, переживает ли job-state рестарт uvicorn (in-memory vs persistent).

---

## 7. Открытые моменты / риски

- Legacy **Streamlit + МойСклад** (`src/`, `pages/`) параллельно с 2.0 — не смешивать write-path.
- **In-memory job lock** — не работает при нескольких uvicorn workers; для prod нужен distributed lock.
- **115 категорий** без auto-seed формулы — донастройка в `/templates`.
- **Mock vehicle directory** — замена на Base-Auto отдельным спринтом.
- **`naming_status` SQL-фильтр** — аппроксимация; в редких случаях может расходиться с badge после live-enrichment.
- `DRY_RUN=true` в `.env` — mass push / job «Массовая отправка» не пишет в Odoo без `DRY_RUN=false` или CLI `--force-apply`.
- **`data/odoo_master_catalog.jsonl`** обязателен для job enrich (не в Git).

---

*Handoff актуален на конец сессии: Main Dashboard + KPI, Background Jobs API, серверная фильтрация каталога, sync error logging, Manual Override (`name_locked` + PATCH override). Следующий фокус — **Live Job Progress** в дашборде.*
