# NameForge — контекст для технического руководителя и ревьюера

Документ для онбординга, сопровождения разработки в **Cursor** и code review.  
**Аудитория:** Tech Lead, senior-ревьюер, внешний разработчик.  
**Обновлять** при смене архитектуры, интеграций или критичных правил.

---

## 1. Краткая сводка (30 секунд)

| Поле | Значение |
|------|----------|
| **Проект** | NameForge — PIM-инструмент для канонических наименований автозапчастей |
| **Каталог** | ~16 000 SKU, автозапчасти и аксессуары |
| **Репозиторий** | Private: `https://github.com/Arsenal0001/NameForge` |
| **Ветка по умолчанию** | `main` |
| **Локальный путь** | `C:\PyProject\NameForge` |
| **Оператор** | Один основной пользователь (desktop), до 5 модераторов в перспективе |
| **Статус** | **Две параллельные линии:** legacy MVP (Streamlit + МойСклад) — production-ready; **NameForge 2.0** (FastAPI + React + Odoo) — в активной миграции |

**Бизнес-цель:** человекочитаемые имена и описания из атомарных атрибутов, согласованные с «Золотым каталогом», синхронизация с ERP, совместимость с **`AutoPrice_Matcher_v2`** (FAISS/SBERT).

---

## 2. Две архитектурные линии (критично для ревью)

Проект **не монолитный**. Любой PR должен явно указывать, какую линию затрагивает.

### 2.1 Legacy MVP — Streamlit + SQLite + МойСклад

| Аспект | Детали |
|--------|--------|
| **UI** | `app.py`, `pages/` (7 страниц) |
| **Логика** | `src/` — workflow, генератор, парсер, клиент API |
| **БД** | `sqlite3` stdlib, **без ORM** — `src/db.py`, `data/autoname.db` |
| **ERP** | МойСклад REST — **только** через `src/moysklad_client.py` |
| **Статус** | Phase D завершена; рабочий инструмент оператора |
| **Документы** | `docs/HANDOFF.md`, `docs/OPERATOR.md`, `DEVELOPMENT_PLAN.md` |

### 2.2 NameForge 2.0 — FastAPI + React + Odoo 19

| Аспект | Детали |
|--------|--------|
| **Backend** | `backend/` — FastAPI, SQLAlchemy 2.0 (sync), Pydantic v2 |
| **Frontend** | `frontend/` — React, TS, Vite, Tailwind, shadcn/ui, TanStack Query |
| **ERP (целевой)** | Odoo 19 Community — JSON-RPC `execute_kw` (**не** XML-RPC) |
| **Правила имён** | `NAMING_TEMPLATES_V2.md`, `backend/app/services/template_service.py` |
| **Статус** | Phase 1 и часть Phase 4 — DONE; Phase 2–3, 5–6 — IN PROGRESS |
| **Документы** | `PROJECT_PASSPORT.md`, `DEVELOPMENT_PLAN_V2.md`, `odoo_api_knowledge.md` |

**Правило для ревью:** не переносить бизнес-логику между линиями «вслепую». Legacy — эталон поведения для МойСклад; 2.0 — новый канал через Odoo. Общие **доменные** правила (шаблоны, анти-таутология, FAISS-ограничения) — в `NAMING_TEMPLATES_V2.md`.

---

## 3. Системный контекст и смежные проекты

```
┌─────────────────┐     import/sync      ┌──────────────────┐
│   МойСклад      │ ◄──────────────────► │ Legacy NameForge │
│  (legacy ERP)   │                      │ Streamlit+SQLite │
└─────────────────┘                      └────────┬─────────┘
                                                  │
┌─────────────────┐     JSON-RPC         ┌────────▼─────────┐
│   Odoo 19       │ ◄──────────────────► │ NameForge 2.0    │
│  (целевой ERP)  │                      │ FastAPI+React    │
└────────┬────────┘                      └────────┬─────────┘
         │                                        │
         │  product.template, attributes          │ generate name + search_keywords
         ▼                                        ▼
┌─────────────────────────────────────────────────────────────┐
│              AutoPrice_Matcher_v2 (Arsenal0001)             │
│         FAISS / SBERT — матчинг прайсов к номенклатуре       │
└─────────────────────────────────────────────────────────────┘
```

**Связь с AutoPrice_Matcher_v2:** в итоговое имя **нельзя** класть артикул и транслит брендов; «Универсальный» вырезается для большинства категорий; единицы нормализуются (`1000мл` → `1 л`). Подробно — раздел 2 в `NAMING_TEMPLATES_V2.md`.

**Мастер-каталог Odoo:** `data/odoo_master_catalog.jsonl` / `.xlsx` — эталон структуры (~15 800 позиций), получен LLM-парсингом (`PROJECT_CONTEXT.md`). **В Git не коммитится** (конфиденциальные товарные данные).

---

## 4. Доменная модель (общая для обеих линий)

### 4.1 Workflow товара (legacy)

Статусы: `new` → `review` → `approved` | `error` | `locked`.

- **`review`** — только когда `candidate_hash != source_hash` (данные изменились).
- **`name_locked = 1`** — имя **никогда** не перезаписывается при sync/approve.
- **`source_hash`** — идемпотентность: PUT/PATCH в ERP только при изменении хэша.

### 4.2 Генерация имён

- **Pure functions:** `generate_name()`, `compute_source_hash()` — **без I/O** (см. `.cursor/rules/04_generation.mdc`).
- **Primary fitment** — одна основная применимость в **имени**; полный список — в **описании**.
- **`year_to = 0`** — маркер «н.в.» (настоящее время), не «пусто».
- **«для»** в шаблоне — только при наличии пары make + model.
- **Макс. длина имени:** 255 символов.
- **NameForge 2.0:** два выхода — `name` (золотое) и `search_keywords` (синонимы, грязные строки) для отдельного поля Odoo.

### 4.3 Формат «грязных» имён поставщика (legacy parser)

Модуль `src/naming/`: `{{Категория}} >Применимость< [Спеки] [[Бренд]]`.  
~99% импортированных имён содержат теги, но fill rate полей make/model в БД исторически низкий — backlog на массовое обогащение через `name_parser`.

---

## 5. Карта репозитория

```
NameForge/
├── app.py, pages/           # Streamlit UI (legacy)
├── src/                     # Legacy бизнес-логика, МойСклад, SQLite
│   ├── product_workflow.py  # preview, approve, sync, hash — «сердце» legacy
│   ├── moysklad_client.py   # единственная точка HTTP к МойСклад
│   ├── name_generator.py, hash_utils.py, template_engine.py
│   └── naming/              # парсер/валидатор канонического формата
├── backend/                 # NameForge 2.0 API
│   ├── main.py              # FastAPI, routers
│   └── app/
│       ├── api/             # catalog, categories, naming, odoo, health
│       ├── models/          # SQLAlchemy
│       ├── services/        # template_service, odoo_client, odoo_catalog_sync
│       └── schemas/         # Pydantic DTO
├── frontend/                # React SPA (каталог, маппинг категорий)
├── scripts/                 # import, audit, seed, mass sync
├── tests/                   # pytest (97 тестов на момент документа)
├── config/attr_map.json     # маппинг атрибутов МойСклад (legacy)
├── data/                    # autoname.db, локальные выгрузки (не всё в Git)
├── migrations/              # SQL-патчи схемы
├── docs/                    # HANDOFF, OPERATOR, этот файл
└── .cursor/rules/           # правила для AI в Cursor
```

### Ключевые точки входа

| Задача | Команда / файл |
|--------|----------------|
| Legacy UI | `python -m streamlit run app.py` |
| Импорт из МС | `python scripts/import_from_ms.py` |
| Backend 2.0 | `cd backend && uvicorn main:app --reload --port 8000` |
| Frontend 2.0 | `cd frontend && npm run dev` (порт 5173) |
| Тесты | `.venv\Scripts\python.exe -m pytest` |
| Линтер | `ruff check .` |

---

## 6. Конфигурация и безопасность

### 6.1 Переменные окружения (`.env`)

**Не коммитить.** Образец — `.env.example`.

| Переменная | Линия | Назначение |
|------------|-------|------------|
| `MOYSKLAD_TOKEN` / `MS_TOKEN` / `MS_API_TOKEN` | Legacy | API МойСклад |
| `MS_LOGIN`, `MS_PASSWORD` | Legacy | альтернатива токену |
| `DRY_RUN` | Legacy | **`true` по умолчанию** — без реальных PUT |
| `DB_PATH` | Legacy | путь к SQLite (default: `data/autoname.db`) |
| `DATABASE_URL` | 2.0 | SQLAlchemy URL |
| `ODOO_URL`, `ODOO_DB`, `ODOO_UID` | 2.0 | Odoo JSON-RPC |
| `ODOO_API_KEY` / `ODOO_PASSWORD` | 2.0 | секрет RPC (см. `odoo_api_knowledge.md`) |
| `ODOO_USER` | 2.0 | учётная запись (справочно) |

### 6.2 Что исключено из Git (`.gitignore`)

- `.env`, `.env.*` (кроме `.env.example`)
- `*.db`, `*.sqlite*`
- `**/.venv/`, кэши pytest/ruff
- `data/odoo_master_catalog.jsonl`, `.xlsx`
- `logs/`, `analysis_output.json`
- `.streamlit/secrets.toml`

### 6.3 Обязательные проверки перед merge

1. В diff **нет** секретов, токенов, дампов БД, полного каталога.
2. Запись в МойСклад/Odoo — за флагом dry-run / явным подтверждением оператора.
3. HTTP к МойСклад — **только** `src/moysklad_client.py`.
4. Odoo — **только** JSON-RPC `/jsonrpc` + `execute_kw` (`odoo_api_knowledge.md`).
5. **`name_locked`** и **`source_hash`** не обходятся без ADR/согласования.

---

## 7. Правила Cursor для AI-агентов

Файлы в `.cursor/rules/` — **источник истины** для автоматических правок:

| Файл | Область |
|------|---------|
| `00_project.mdc` | глобально: dry-run, hash, SQLite без ORM, Ruff, EN code / RU UI |
| `02_moysklad_api.mdc` | клиент МойСклад, лимиты, attr_map |
| `03_streamlit_ui.mdc` | Streamlit, русские строки UI |
| `04_generation.mdc` | pure functions, fitment, длина имени |
| `05_database.mdc` | SQLite, схема, триггеры |
| `06_testing.mdc` | pytest, mocks, in-memory DB |
| `odoo_catalog_parsing.mdc` | парсинг золотого каталога |

**Handoff для новой сессии AI:** `docs/HANDOFF.md` (legacy-фокус) + этот документ + `PROJECT_PASSPORT.md` (2.0).

### Рекомендуемый промпт для Tech Lead в Cursor

> Ты технический руководитель NameForge. Прочитай `docs/TECH_LEAD_REVIEW_CONTEXT.md`, определи линию (legacy / 2.0), проверь `.cursor/rules/`, не ломай dry-run, source_hash, name_locked. Минимальный diff, pytest green, ruff clean.

---

## 8. Code review — чеклист

### 8.1 Общее

- [ ] Изменения относятся к одной линии или миграция явно описана в PR/commit message.
- [ ] Scope минимален; нет «заодно» рефакторинга.
- [ ] Код и docstrings — **English**; UI/сообщения Streamlit — **Russian**.
- [ ] `ruff check .` без новых ошибок.
- [ ] `pytest` — все тесты зелёные (97+).

### 8.2 Legacy (Streamlit / МойСклад)

- [ ] Нет ORM в `src/`; только `sqlite3`.
- [ ] Нет прямых `requests` к МойСклад вне `moysklad_client.py`.
- [ ] Нет hardcoded UUID атрибутов — `config/attr_map.json`.
- [ ] `settings.dry_run` проверяется перед записью в API.
- [ ] Sync только при изменении `source_hash`.
- [ ] `name_locked` respected в approve/sync/preview flows.

### 8.3 NameForge 2.0 (FastAPI / Odoo)

- [ ] DTO на границах API — Pydantic schemas в `backend/app/schemas/`.
- [ ] Odoo: JSON-RPC, не XML-RPC; не `authenticate` / session login.
- [ ] `template_service.py` соблюдает **три золотых правила** и запрет SKU/транслита в `name`.
- [ ] CORS и origins согласованы с `frontend` (localhost:5173).
- [ ] Изменения схемы БД — models + `schema_patches` / миграции.

### 8.4 Данные и конфиденциальность

- [ ] Нет коммита `.env`, `.db`, jsonl/xlsx каталога.
- [ ] Нет логирования токенов и паролей.
- [ ] Скриншоты оператора / внутренние отчёты — не в публичных артефактах без необходимости.

---

## 9. Тестирование

- **Runner:** pytest, каталог `tests/`.
- **Legacy repos:** in-memory SQLite (`:memory:`), не трогать рабочую `data/autoname.db`.
- **moysklad_client:** mocks, без сети.
- **name_generator / hash_utils:** детерминированные unit-тесты, без I/O.

Перед handoff или merge: `.venv\Scripts\python.exe -m pytest`.

---

## 10. Текущий backlog (приоритеты)

### Legacy / операционный

| Приоритет | Задача |
|-----------|--------|
| **HIGH** | Массовое обогащение БД через `src/naming/name_parser` из `supplier_raw_name` |
| **MEDIUM** | Категорийные шаблоны (сейчас базовые `fitment_base` / `universal_base`) |
| **LOW** | Эвристики make по model в `fitment_parser.py` |

### NameForge 2.0 (по `DEVELOPMENT_PLAN_V2.md`)

| Фаза | Статус |
|------|--------|
| 1 Scaffolding | DONE |
| 2 DB Schema & Migration | IN PROGRESS |
| 3 Odoo Integration | частично (`odoo_client.py`, API routes) |
| 4 Naming Engine | частично DONE (`template_service`, naming API) |
| 5 Frontend | IN PROGRESS (каталог, category mapping) |
| 6 Deployment | не начата |

### Известный технический долг (для ревьюера)

- `backend/app/core/config.py` — в коде `odoo_client.py` ожидаются `ODOO_UID` и `odoo_api_secret()`; убедиться, что Settings и `.env.example` синхронизированы перед прод-интеграцией.
- Дублирование frontend: `frontend/` и `backend/frontend/` — уточнять активный каталог перед правками UI.
- Документы `HANDOFF.md` (МойСклад) и `PROJECT_PASSPORT.md` (Odoo) описывают разные «целевые» ERP — это осознанный переходный период.

---

## 11. Git и процесс разработки

| Параметр | Значение |
|----------|----------|
| Remote | `origin` → `https://github.com/Arsenal0001/NameForge.git` |
| Ветка | `main` (tracking `origin/main`) |
| Видимость | **Private** |
| Аутентификация | HTTPS + Personal Access Token (Git Credential Manager) |

**Рабочий цикл:** правки → `git add` (staging) → `git commit` → `git push`.  
В Cursor: Source Control (Ctrl+Shift+G); глобально включены `git.confirmSync`, запрет force-push из UI.

**Коммиты:** осмысленные сообщения на English; один логический change per commit где возможно.

---

## 12. Открытые архитектурные вопросы

1. Несколько primary fitment в имени — сейчас **строго одна**; нужно ли расширение?
2. Бренды-заглушки (`NON`, `?`, `н/а`) — исключать из `{brand}` (текущее решение).
3. Момент «выключения» legacy МойСклад-линии после паритета 2.0 + Odoo.
4. PostgreSQL на VPS vs SQLite локально — единый `DATABASE_URL` уже заложен в 2.0.

---

## 13. Порядок чтения документов

| Роль | Файлы |
|------|-------|
| **Tech Lead (обзор)** | этот файл → `PROJECT_PASSPORT.md` → `DEVELOPMENT_PLAN_V2.md` |
| **Ревью legacy PR** | `docs/HANDOFF.md` → `PROJECT_CONTEXT.md` (нижние секции про MVP) → `.cursor/rules/` |
| **Ревью 2.0 PR** | `NAMING_TEMPLATES_V2.md` → `odoo_api_knowledge.md` → `backend/app/services/template_service.py` |
| **Оператор** | `docs/OPERATOR.md` |
| **Домен Odoo-каталога** | `PROJECT_CONTEXT.md` (LLM pipeline, golden_type) |

---

## 14. Версия документа

| Поле | Значение |
|------|----------|
| Файл | `docs/TECH_LEAD_REVIEW_CONTEXT.md` |
| Создан | 2026-05-22 |
| Git baseline | commits `402db39`, `dfe2f25` on `main` |
| Следующее обновление | при завершении Phase 2–3 в 2.0 или смене ERP-стратегии |
