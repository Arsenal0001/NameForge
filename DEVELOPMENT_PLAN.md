# План разработки приложения AutoName (NameForge)

Документ фиксирует согласованную архитектуру и дорожную карту MVP приложения автоматической генерации наименований и описаний товаров автозапчастей для **МойСклад**. Предназначен для контекста в новых диалогах разработки; детали контрактов см. также [`PROJECT_CONTEXT.md`](PROJECT_CONTEXT.md).

---

## 1. Роль документа и связь с кодом

| Артефакт | Назначение |
|----------|------------|
| **`DEVELOPMENT_PLAN.md`** (этот файл) | Стратегический план, roadmap, обзор модулей, решения высокого уровня |
| **`PROJECT_CONTEXT.md`** | Нормативные правила домена (hash, статусы, описание, границы backend/UI) |
| **`src/db.py`** | DDL SQLite, константы enum, `init_db`, `get_conn`; опционально `DB_PATH` для тестов |

---

## 2. Продукт и цели MVP

**Проблема:** в МойСклад поиск только по `name`, `article`, `code`; у справочников одно значение на поле; множественная применимость и сложные имена нельзя выразить без внешнего слоя.

**Решение:** desktop-приложение на **Python + Streamlit** с локальной **SQLite** как источником истины для fitment-матрицы, шаблонов имён и алиасов; синхронизация с МойСклад по **REST API**.

**Цели MVP:**

- Два режима каталога: **`fitment`** и **`universal`** (~30–50% SKU без применимости).
- Два базовых шаблона имени: **`fitment_base`**, **`universal_base`** (без категорийной специфики до следующих фаз).
- Полуавтоматический контур: preview → очередь → подтверждение → PATCH в МойСклад.
- Один оператор; каталог порядка **16 000** позиций — без избыточной серверной инфраструктуры на первом этапе.

**Нецели MVP:** отдельный продакшен-микросервис, PostgreSQL, многопользовательская роль-модель, сложная агрегация нескольких марок в имени товара.

---

## 3. Архитектура системы

```
┌─────────────────────────────────────────────────────────────┐
│ МойСклад (облако)                                             │
│ Витрина: name, article, code, description + кастомные поля   │
└───────────────────────────┬─────────────────────────────────┘
                            │ REST JSON API (read/write)
┌───────────────────────────▼─────────────────────────────────┐
│ Streamlit desktop — очередь, карточка, шаблоны, алиасы          │
│ Ephemeral: preview_name, preview_description, candidate_hash  │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│ SQLite (локально, data/autoname.db по умолчанию)             │
│ Истина: products, fitments, templates, aliases                │
└─────────────────────────────────────────────────────────────┘
```

**Принцип разделения:**

- **МойСклад** — то, что видят менеджеры и что участвует в поиске по штатному поиску (`name` несёт ключевой контекст для марки/модели).
- **SQLite** — полная применимость, версии шаблонов, хэш источника, алиасы нормализации.
- **Session state** — только черновики генерации до подтверждения.

---

## 4. Стек технологий

| Слой | Технология |
|------|------------|
| UI | Streamlit (`app.py`, `pages/`) |
| Язык | Python 3 |
| Локальная БД | SQLite (`sqlite3`, WAL, foreign keys) |
| Валидация моделей | Pydantic (товары/fitment в коде) |
| HTTP к МойСклад | `requests` ([`src/moysklad_client.py`](src/moysklad_client.py)) |
| Хэширование | `hashlib` + канонический JSON ([`src/hash_utils.py`](src/hash_utils.py)) |
| Генерация имени/описания | [`src/name_generator.py`](src/name_generator.py) |
| Fitment CRUD | [`src/fitment_repo.py`](src/fitment_repo.py) |
| Шаблоны (будущее расширение) | [`src/template_engine.py`](src/template_engine.py) — по мере необходимости |

---

## 5. Данные и границы ответственности

### 5.1 SQLite

Таблицы: **`templates`**, **`products`**, **`fitments`**, **`aliases`** — см. DDL в `src/db.py` и таблицы в `PROJECT_CONTEXT.md`.

Ключевые инварианты:

- Одна строка fitment с **`is_primary = 1`** на товар (partial unique index).
- **`source_hash`** хранит только последний подтверждённый снимок; **`generation_status`** по умолчанию **`new`**, пустой хэш допускается через **`DEFAULT ''`**.

### 5.2 МойСклад

- Шаблоны текста имени живут в SQLite; в облаке — только ключи **`template_key`** / **`template_version`** (после интеграции с карточкой).
- Имя атрибута статуса генерации для фильтрации в API-клиенте задаётся константой (например **`generation_status`**) — должен совпадать с именем атрибута в метаданных аккаунта.

### 5.3 Константы приложения

Определены в коде (не `CHECK` в SQLite): **`ALIAS_TYPES`**, **`GENERATION_STATUSES`**, **`APPLICABILITY_TYPES`** — см. `src/db.py`.

---

## 6. Доменная логика (кратко)

### 6.1 Режимы **`fitment`** / **`universal`**

| Режим | Fitment UI | Primary в имени |
|-------|-------------|-------------------|
| `fitment` | Редактор строк применимости | Только primary fitment |
| `universal` | Скрыт | Из полей продукта / шаблона без fitment |

### 6.2 Годы для отображения

- **`year_to = 0`** — валидный маркер «н.в.» (не пустота).
- Форматирование — **`format_years`** в `name_generator`; то же используется в **`build_fitment_summary`** в fitment_repo.

### 6.3 Хэш источника

- **`compute_source_hash`** (`hash_utils`): универсальный набор полей + для `fitment` дополнительно primary и отсортированные сегменты строк fitment (**`year_to=0`** входит как **`"0"`** в строке сегмента).

### 6.4 Статусы генерации

- Переход в **`review`** только если **`candidate_hash ≠ source_hash`** после успешного preview.
- После **`unlock_name`**: **`review`**, если **`source_hash ≠ ''`**, иначе **`new`**.

Подробнее — **`PROJECT_CONTEXT.md`** (разделы про hash и статусы).

---

## 7. Планируемые модули приложения (`src/`)

| Модуль | Статус назначения |
|--------|-------------------|
| [`db.py`](src/db.py) | Инициализация БД, подключение, константы |
| [`moysklad_client.py`](src/moysklad_client.py) | Клиент API: metadata, список товаров, GET/PATCH; `patch_product(..., directory_cache=, brand=)` для customentity «Бренд» |
| [`fitment_repo.py`](src/fitment_repo.py) | Транзакции fitment + синхронизация primary в `products` |
| [`name_generator.py`](src/name_generator.py) | `GeneratedName`, шаблоны MVP, `description` |
| [`hash_utils.py`](src/hash_utils.py) | `compute_source_hash` |
| [`template_engine.py`](src/template_engine.py) | Расширяемая подстановка шаблонов (по мере роста) |
| [`directory_cache.py`](src/directory_cache.py) | Кэш customentity (справочник «Бренд»): загрузка строк API, `resolve` / `resolve_brand` → `meta` для PATCH |
| [`fitment_parser.py`](src/fitment_parser.py) | Токен `>…<` в имени поставщика + эвристика марки (напр. ВАЗ по модели) при импорте |
| [`product_workflow.py`](src/product_workflow.py) | Правила preview→статус, NF PATCH payload, `approve_and_sync_execute` (операции 4–5, 7, 8–9 из `PROJECT_CONTEXT`) |

**Сервисный слой** — вынесен в `src/product_workflow.py`; страницы Streamlit вызывают его для единых правил и тестов.

---

## 8. UI (Streamlit)

Запланированные страницы:

| Страница | Файл | Функция |
|----------|------|---------|
| Очередь | `pages/01_queue.py` | Фильтры, batch preview/approve (лимит **50**, задержка **0.1 s** между PATCH) |
| Карточка | `pages/02_card.py` | Поля товара, fitment-редактор (pin primary), preview |
| Шаблоны | `pages/03_templates.py` | Версии шаблонов в SQLite |
| Алиасы | `pages/04_aliases.py` | Справочник нормализации |
| Синхронизация | `pages/05_sync.py` | Предпросмотр, утверждение, пакетная генерация/review-sync с МойСклад |

Боковая панель: токен API, путь к БД, **`dry_run`**, обновление кэшей.

Конфигурация: **`.env`** / **`.env.example`** — путь к БД, токен МойСклад.

---

## 9. Этапы разработки (roadmap)

### Фаза A — Завершение ядра (текущая база кода)

- [x] SQLite DDL и репозиторий fitment  
- [x] Генератор имени/описания и хэш  
- [x] Клиент МойСклад с мок-тестами  
- [x] Юнит-тесты fitment_repo, name_generator, hash_utils  
- [x] Сервисный слой: `src/product_workflow.py` (правила preview/статусов, `approve_and_sync_execute`, NF payload); UI остаётся в `pages/`  

### Фаза B — UI Streamlit

- [x] Подключение `.env`, инициализация БД при старте (`app.py`)  
- [x] Экран очереди и карточки с `session_state` для preview (`pages/01_queue.py`, `pages/02_card.py`)  
- [x] Страница шаблонов (CRUD в `templates`, `pages/03_templates.py`)  
- [x] Страница алиасов (`pages/04_aliases.py`)  

### Фаза C — Эксплуатация

- [x] Импорт товаров из МойСклад в SQLite (`scripts/import_from_ms.py`, `external_code`, `ms_product_id`)  
- [x] Настройка атрибутов: `config/attr_map.json`, `scripts/setup_ms_attributes.py`, загрузка карты в `MoySkladClient`  
- [x] Документация запуска для оператора — `docs/OPERATOR.md`  
- [x] Production: `DirectoryCache` + резолв customentity «Бренд» в `MoySkladClient.patch_product` (опционально `directory_cache` + `brand`)  
- [x] Production: парсер `>fitment<` в `fitment_parser.py` и дозаполнение `primary_make`/`primary_model` при импорте, если марка в МС пустая  
- [x] Production: бренды **NON**, **?**, **н/а** и пустой бренд — не ошибка генерации: токен `{brand}` опускается, в `warnings` — `brand_skipped: …` (`name_generator.SKIP_BRANDS`)  

### Фаза D — Production Hardening (ЗАВЕРШЕНО)

- [x] D1: Полный импорт и аудит данных (`docs/IMPORT_AUDIT.md`).
- [x] D2: Модуль `src/naming/` (парсер, валидатор, страница UI).
- [x] D3: Расширение `product_workflow` (refresh из МС, batch preview).
- [x] D4: Финализация UI (вкладка ошибок, разблокировка) и валидация `.env`.

### Фаза E — Эксплуатация и обогащение (ТЕКУЩАЯ)

- [ ] Массовый парсинг `supplier_raw_name` для заполнения `brand` и `part_type`.
- [ ] Категорийные шаблоны имен.
- [ ] Оптимизация эвристик применимости.

---

## 10. Риски и принятые решения

| Риск | Митигация |
|------|-----------|
| Поиск только по `name` / `article` / `code` | Ключевая марка/модель и контекст в **`name`**; не раздувать имя полным fitment |
| Один справочник на поле в МойСклад | Primary + полный список в SQLite + текст **`description`** |
| Дрейф шаблонов | Версии в SQLite + **`source_hash`** |
| Лимиты API | Batch ≤ **50**, **`sleep(0.1)`** между PATCH, retry **429** в клиенте |
| Бренд в PATCH как строка для customentity «Бренд» | МойСклад игнорирует значение без **meta**; передавать `DirectoryCache.resolve_brand` + `patch_product(..., directory_cache=…, brand=…)` |
| Плейсхолдер **NON** / **?** в шаблоне | Не считать ошибкой домена: генерировать имя без маркера-заглушки, фиксировать предупреждение для оператора |

---

## 11. Тестирование

- **pytest**, изоляция БД через **`DB_PATH`** и временный файл в **`tmp_path`** (`tests/test_fitment_repo.py`).  
- МойСклад: **`unittest.mock`** на `session.request`, без реальных вызовов (`tests/test_moysklad_client.py`).  
- Чистые функции: **`tests/test_name_generator.py`**, **`tests/test_hash_utils.py`**.

Конфигурация: **`pytest.ini`** (`pythonpath = .`).

---

## 12. Как ссылаться на этот план в новом чате

Рекомендуемая формулировка для контекста:

> Проект **NameForge** (`c:\PyProject\NameForge`): desktop **Streamlit** + локальная **SQLite** + API **МойСклад**. Архитектура и этапы — **`DEVELOPMENT_PLAN.md`**; правила домена (hash, статусы, описание) — **`PROJECT_CONTEXT.md`**. Реализация в **`src/`**.

---

## 13. История документа

| Версия | Содержание |
|--------|------------|
| 1.0 | Первичное оформление плана по контексту чата разработки AutoName MVP |

---

*При изменении архитектуры обновляйте этот файл и `PROJECT_CONTEXT.md` синхронно.*
