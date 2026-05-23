# Odoo API integration — NameForge 2.0

## 1. Environment

| Item | Value |
|------|--------|
| **Odoo version** | **19.0 Community** (stable), VPS `https://erp.arszap.ru` |
| **Database** | `stable_arszap` |
| **Protocol** | **JSON-RPC only** — `POST {ODOO_URL}/jsonrpc`, method `execute_kw` |
| **API account** | Dedicated user for NameForge 2.0 (not operator UI login) |

NameForge 2.0 (FastAPI + React) runs **locally**; Odoo is remote. Deploy of 2.0 to VPS is planned later.

## 2. Mandatory rules for all Odoo code

1. **Do not** use `common.authenticate`, `/web/session/authenticate`, or cookie sessions.
2. **Do not** use `xmlrpc.client`. Use `requests` + JSON-RPC.
3. **Always** call `execute_kw` on service `object` via `/jsonrpc`.
4. **Always** pass `(db, uid, api_secret, model, method, args, kwargs)` in every RPC call.
5. **Always** read credentials from project-root `.env` via `backend/app/core/config.py`.
6. **All Odoo HTTP** goes only through `backend/app/services/odoo_client.py`.

## 3. Client implementation

Canonical client: `backend/app/services/odoo_client.py` (`OdooClient`).

```python
payload = {
    "jsonrpc": "2.0",
    "id": rpc_id,
    "method": "call",
    "params": {
        "service": "object",
        "method": "execute_kw",
        "args": [db, uid, api_secret, model, method, positional_args, keyword_args],
    },
}
```

Helper methods:

- `search_read(model, domain, fields, limit=…)` — catalog reads
- `get_product_template_by_default_code(default_code)` — smoke test / lookup by SKU
- `test_connection()` — `res.users.read` for configured `ODOO_UID`

## 4. Environment variables (`.env`)

```ini
DATABASE_URL=sqlite:///./data/autoname.db
ODOO_URL=https://erp.arszap.ru
ODOO_DB=stable_arszap
ODOO_UID=5
ODOO_API_KEY=
ODOO_USER=nameforge-api@example.com
ODOO_PASSWORD=
```

| Variable | Required | Notes |
|----------|----------|--------|
| `ODOO_URL` | yes | Base URL without trailing slash |
| `ODOO_DB` | yes | Odoo database name |
| `ODOO_UID` | yes | Integer `res.users.id` of the API account |
| `ODOO_API_KEY` | preferred | 40-char API key from Odoo user profile |
| `ODOO_PASSWORD` | fallback | Used as RPC secret when `ODOO_API_KEY` is empty |
| `ODOO_USER` | optional | Login label for documentation / ops |

**Secret resolution:** `ODOO_API_KEY` if set, else `ODOO_PASSWORD`.

## 5. Verification endpoints (local FastAPI)

| Endpoint | Purpose |
|----------|---------|
| `GET /api/odoo/ping` | Auth + connectivity via `res.users.read` |
| `GET /api/odoo/product-template?default_code=DISC` | Read one `product.template` by article |

Example:

```bash
curl "http://127.0.0.1:8000/api/odoo/product-template?default_code=DISC"
```

## 6. Catalog best practices

- **Primary key for import:** `default_code` (article / SKU).
- **Chunked reads:** `search_read` in batches of 100–500 to avoid Nginx timeouts.
- **Writes:** respect local `name_locked` and idempotency before pushing names to Odoo.
- **Pure naming logic:** generation stays in `template_service` / naming modules — no Odoo I/O inside generators.

## 7. Why direct `execute_kw` (historical note)

On some alpha builds, `authenticate` and session login failed with custom auth modules (2FA, Roles). Stable **19.0 Community** on `erp.arszap.ru` works with a dedicated API user + explicit `ODOO_UID` + API key via direct `execute_kw`. Session-based login remains **out of scope** for NameForge 2.0.
