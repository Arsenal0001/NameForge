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

**Локализация RPC (критично):** все вызовы `execute_kw` через `OdooClient` принудительно получают `kwargs={"context": {"lang": "ru_RU"}}`. Без этого `product.template.name` (переводимое поле) пишется в `en_US`, а UI показывает старый `ru_RU`.

**Запуск (локально):**
```bash
# Backend
cd backend && uvicorn main:app --reload --port 8000

# Frontend (proxy /api → :8000)
cd frontend && npm run dev   # http://localhost:5173
```

**Маршруты SPA:**
- `/` — **Главный дашборд** (KPI + Quick Actions + прогресс фоновых jobs)
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

**Transport:**
- Пакетный JSON-RPC-массив в одном HTTP POST давал **`HTTP 400`** на `erp.arszap.ru`.
- **Исправлено:** `OdooClient.batch_write()` и `SyncService._flush_writes()` — **последовательные** `write` по одному товару, с `try/except` на каждый ID.

**Push payload (`SyncService`):**
- `name` + `x_search_keywords` на `product.template`
- `attribute_line_ids` — нативные атрибуты Odoo (см. §2.2)
- Preview-first: для незабlocked товаров в Odoo уходит **свежий preview**, а не stale `generated_name`

**Background Jobs (`backend/app/api/routers/jobs.py`):**
- Немедленный ответ **`202 Accepted`**; работа в `BackgroundTasks` FastAPI.
- **In-memory mutex** (`job_lock.py`): повторный запуск → **`409 Conflict`**.
- **Job progress (DONE):** `GET /api/jobs/active`, виджет на `MainDashboard.tsx`.

**Рекомендуемый порядок полного цикла (CLI):**
```bash
python scripts/sync_odoo_categories.py
python scripts/sync_catalog_from_odoo.py
python scripts/enrich_catalog_from_jsonl.py --apply
python scripts/seed_templates_from_jsonl.py --apply   # odoo_categories.name_pattern
python scripts/mass_sync_to_odoo.py               # DRY_RUN симуляция
python scripts/mass_sync_to_odoo.py --force-apply # live → erp.arszap.ru
```

**Canary E2E (точечная проверка 5 SKU):**
```bash
python scripts/run_canary_test.py   # TARGET_CODES: 04966, 06575, 11064, 17128, 16300
```
При старте выводит **`Odoo target DB: 'stable_arszap'`** — сверить с базой в браузере. После Load — **Verification Read** (`search_read` в `ru_RU`) и колонка «Имя после проверки в Odoo».

### 2.2 Атрибуты и именование — DONE (Priority Weights + Native Odoo Attributes)

| Компонент | Назначение |
|-----------|------------|
| **`attribute_parser.py`** | `PRIORITY_WEIGHTS` + `sort_attribute_keys()` — **детерминированная сортировка** JSONL-ключей **до** склейки в строку. Тир 1 (10): ядро (`power_kw`, `volume_ml`, …). Тир 2 (20): геометрия (`teeth_count`, `diameter_mm`, …). Тир 3 (30): состав/технологии. Тир 4 (40): визуал (`form_factor`, `color`). Тир 99: прочие. |
| **`products.attribute_summary`** | Русская строка характеристик для `{attributes}` в шаблоне |
| **`products.attributes_json`** | Сырой JSONL `attributes` dict — источник для Odoo attribute sync |
| **`odoo_attribute_sync.py`** | Upsert `product.attribute` / `product.attribute.value`; привязка к `product.template` через `attribute_line_ids`. Маппинг JSONL → Odoo (`power_kw` → «Мощность», `color` → «Цвет», …). **`create_variant: "no_variant"`** — без генерации вариантов SKU. Ошибки атрибутов — `try/except`, **не блокируют** запись имени. |
| **`template_service.py`** | Категорийные `name_pattern` из `odoo_categories` (TemplateEngine). Smart Auto-Injection **отключена** — только формула шаблона. |
| **`text_utils.py`** | Golden postprocess, anti-tautology (с сохранением prefix `part_type`), нормализация единиц |
| **`seed_templates_from_jsonl.py`** | Registry + `CATEGORY_GROUP_OVERRIDES` для смешанных групп (Стартеры, Антикор) |

**Примеры порядка (канарейка):**
- `06575`: `1000 мл Аэрозоль Черный` → имя `Антигравий 1 л Аэрозоль Черный MASTERWAX`
- `04966`: `1.2 кВт 11 зубьев` → имя `Стартер для Lada Priora (2170) 1.2 кВт 11 зубьев VALEO`

**Канареечный тест — подтверждено оператором:**
- **100% Success** записи **имён** в Odoo UI (`ru_RU`)
- **100% Success** заполнения вкладки **«Атрибуты и варианты»** нативными `product.attribute`

### 2.3 Главный дашборд — DONE

| Компонент | Назначение |
|-----------|------------|
| **`GET /api/metrics/dashboard`** | KPI: `total_products`, `synced`, `pending`, `locked` |
| **`GET /api/jobs/active`** | Статус/прогресс фоновых ETL-jobs |
| **`MainDashboard.tsx`** | KPI + Quick Actions + progress bar активных задач |

### 2.4 Data Grid, Manual Override, Fitment — DONE

Серверные фильтры, `last_sync_error`, `PATCH /api/products/{id}/override`, `name_locked` semantics, fitment API.

---

## 3. Golden Rules (не ломать — непреклонно)

1. **Только JSON-RPC** — `execute_kw` через `OdooClient`. **XML-RPC под абсолютным запретом.**
2. **Запись в Odoo ТОЛЬКО через `SyncService`** — push делегирует в `SyncService.sync_products()`.
3. **Контекст `ru_RU`** — все RPC через `OdooClient` (Translation Context Trap для `product.template.name`).
4. **Идемпотентность (`source_hash`)** — skip только при неизменном hash **и** `synced_at`, **и** отсутствии более свежего `updated_at`.
5. **`name_locked`** — блокирует автогенерацию, **не** блокирует Odoo sync stored `generated_name`.
6. **`DRY_RUN=true` (default)** — симуляция без HTTP write. Live: `DRY_RUN=false` **или** `--force-apply` / canary `force_apply`.
7. **`x_search_keywords`** — обязательное поле при push вместе с `name` на `product.template`.
8. **`create_variant: "no_variant"`** — при создании `product.attribute` через NameForge (запрет вариантов на складе).
9. **Генерация имён — pure function** — `generate_naming_result()` без I/O.
10. **Код EN / UI RU.**

---

## 4. СЛЕДУЮЩИЙ ФОКУС — старт новой сессии здесь

### ✅ Закрыто в этой сессии (не возвращаться)

| Блокер | Решение |
|--------|---------|
| **Data Mismatch (Sync vs Odoo UI)** | `OdooClient._merge_rpc_kwargs()` → `context.lang = ru_RU`; canary Verification Read |
| **Ugly Naming / хаотичный порядок атрибутов** | `PRIORITY_WEIGHTS` в `attribute_parser.py`; профессиональные `name_pattern` в seed; auto-injection удалена |
| **Пустая вкладка «Атрибуты и варианты»** | `odoo_attribute_sync.py` → `attribute_line_ids` upsert в `SyncService` |

### 🎯 New Focus (приоритет следующего спринта)

#### 1. SEO-индексация — `x_search_keywords`

- Обогащение поля **`x_search_keywords`**: склейка синонимов, кросс-номеров, «грязных» supplier-строк, альтернативных названий (ПТФ, туманки, …).
- Цель: ручной поиск оператора в Odoo + совместимость с downstream-пайплайнами.
- **Не путать** с golden `name` (Rule 2 в `NAMING_TEMPLATES_V2.md` — синонимы **не** в печатное имя).

#### 2. Автоматическое тегирование — `product.tag` / `product_tag_ids`

- Авто-присвоение e-commerce тегов на `product.template` для фильтров витрины.
- Upsert по аналогии с attribute sync; idempotent write через `SyncService`.

#### 3. HTML-описания — **ОТЛОЖЕНО**

- Генерацию HTML `description_sale` / rich-text описаний **не начинать** в ближайшем спринте.
- Планируется **позже через LLM** после стабилизации SEO + тегов.

---

## 5. Ключевые файлы (актуальные)

| Область | Путь |
|---------|------|
| **Sync (write gate)** | `sync_service.py`, `odoo_client.py`, `odoo_attribute_sync.py` |
| **Attribute pipeline** | `attribute_parser.py`, `catalog_jsonl_enrichment.py` |
| **Naming engine** | `template_service.py`, `text_utils.py` |
| **Template seed registry** | `scripts/seed_templates_from_jsonl.py` |
| **Canary E2E** | `scripts/run_canary_test.py` |
| **Job progress** | `job_progress.py`, `api/routers/jobs.py` |
| **Dashboard** | `MainDashboard.tsx` |
| **DB patches** | `schema_patches.py` (`attribute_summary`, `attributes_json`, `last_sync_error`, …) |
| **Tests** | `test_sync_service.py`, `test_attribute_parser.py`, `test_odoo_attribute_sync.py`, `test_odoo_client.py`, … |

**Референс:** `NAMING_TEMPLATES_V2.md`, `odoo_master_catalog_notebooklm.pdf`.

---

## 6. Проверки качества (baseline)

```bash
ruff check .
pytest                    # 182 tests green (на момент handoff)
cd frontend && npm run build
```

**Canary regression (5 SKU):**
```bash
python scripts/run_canary_test.py
# Ожидание: Success × 5; attribute_summary в правильном порядке; Odoo UI = Verification Read
```

---

## 7. Открытые моменты / риски

- Legacy **Streamlit + МойСклад** параллельно с 2.0 — не смешивать write-path.
- **In-memory job lock / job progress** — не переживают рестарт uvicorn.
- **`seed_templates_from_jsonl.py --apply`** нужен после обновления registry (категории без `name_pattern` → fallback на SQL `templates`).
- **`data/odoo_master_catalog.jsonl`** обязателен для enrich (не в Git).
- **`DRY_RUN=true`** по умолчанию — mass push без `--force-apply` не пишет в Odoo.
- **Attribute upsert** создаёт глобальные `product.attribute` в Odoo — нужна политика именования и периодический аудит дублей.

---

*Handoff актуален на конец сессии: Priority Weights, native Odoo attributes (`no_variant`), ru_RU RPC context, canary 100% green (имена + атрибуты в UI). **Следующий фокус — SEO (`x_search_keywords`) и auto-tagging (`product.tag`); HTML-описания через LLM — отложены.***
