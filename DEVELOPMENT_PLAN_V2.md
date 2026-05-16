# NameForge 2.0 Development Plan

## Phase 1: Scaffolding (DONE)
- [x] Monorepo structure (backend/ + frontend/)
- [x] Backend: FastAPI + SQLAlchemy + Pydantic v2
- [x] Backend: Health check endpoint (`/api/health`)
- [x] Backend: Database configuration (SQLite/PostgreSQL)
- [x] Frontend: Vite + React + TypeScript + Tailwind CSS
- [x] Frontend: shadcn/ui initialization and basic components
- [x] Environment configuration (.env)

## Phase 2: Database Schema & Migration (IN PROGRESS)
- [ ] Transfer DB schema to `backend/app/models/` (using `src/db.py` as reference)
- [ ] Implement Pydantic schemas for API layer
- [ ] Set up basic CRUD services

## Phase 3: Odoo Integration
- [ ] Create `backend/app/services/odoo_client.py` (XML-RPC)
- [ ] Implement reading: `product.template`, `product.attribute`, `product.category`
- [ ] Implement writing: update `product.template` and attributes

## Phase 4: Naming Engine
**Единый источник правил «Золотого каталога»:** [`NAMING_TEMPLATES_V2.md`](NAMING_TEMPLATES_V2.md) (три правила, матрица типов, ограничения для матчера).

- [x] `backend/app/services/template_service.py` + `text_utils.py`: шаблоны, хэш, `generate_naming_result` (`name`, `search_keywords`), экспорт JSON/txt
- [x] Pydantic `backend/app/schemas/naming.py` (`ProductNamingInput`, `FitmentNamingInput`, `GeneratedNamingResult`, batch DTOs)
- [x] HTTP API: `POST /api/products/{product_id}/generate-name`, `POST /api/products/batch/generate-name` (`backend/app/api/naming.py`)

## Phase 5: Frontend Development
- [ ] Product catalog page (SPA)
- [ ] Template editor
- [ ] Category mapping (Odoo -> Naming Templates)
- [ ] Attribute management

## Phase 6: Deployment & Production
- [ ] PostgreSQL setup on VPS
- [ ] Nginx + systemd configuration
- [ ] Final production testing
