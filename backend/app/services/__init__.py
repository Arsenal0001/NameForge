from app.services.odoo_catalog_sync import sync_odoo_catalog, write_product_template_name
from app.services.odoo_client import OdooClient, OdooClientError
from app.services.template_service import (
    NamingValidationError,
    ProductNotFoundError,
    compute_source_hash,
    export_naming_result,
    generate_for_loaded_product,
    generate_for_product,
    generate_naming_result,
    persist_generation_result,
    product_from_orm,
    resolve_active_template_pattern,
)

__all__ = [
    "NamingValidationError",
    "OdooClient",
    "OdooClientError",
    "ProductNotFoundError",
    "compute_source_hash",
    "export_naming_result",
    "generate_for_loaded_product",
    "generate_for_product",
    "generate_naming_result",
    "persist_generation_result",
    "product_from_orm",
    "resolve_active_template_pattern",
    "sync_odoo_catalog",
    "write_product_template_name",
]
