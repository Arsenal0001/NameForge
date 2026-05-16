from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import catalog, categories, health, naming, odoo
from app.core.database import SessionLocal, engine
from app.core.schema_patches import apply_schema_patches
from app.services.naming_matrix_seed import ensure_matrix_templates


@asynccontextmanager
async def lifespan(app: FastAPI):
    apply_schema_patches(engine)
    db = SessionLocal()
    try:
        ensure_matrix_templates(db)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    yield


app = FastAPI(title="NameForge 2.0 API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api")
app.include_router(catalog.router, prefix="/api")
app.include_router(categories.router, prefix="/api")
app.include_router(naming.router, prefix="/api")
app.include_router(odoo.router, prefix="/api/odoo")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
