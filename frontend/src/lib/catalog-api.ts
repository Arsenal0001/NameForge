export type NamingStatus = "no_template" | "pending_sync" | "synced";

export type ProductCatalogItem = {
  id: number;
  article: string;
  odoo_name: string;
  name: string;
  preview_name: string;
  naming_status: NamingStatus;
  category: string;
  part_type: string;
  applicability_type: string;
  brand: string;
  primary_make: string;
  primary_model: string;
  fitment_summary: string;
  name_locked: boolean;
  category_template_bound: boolean;
  search_keywords: string;
  last_sync_error: string | null;
};

export type CatalogQueryFilters = {
  search?: string;
  naming_status?: NamingStatus;
  is_locked?: boolean;
  has_error?: boolean;
};

export type ProductCatalogPage = {
  items: ProductCatalogItem[];
  total_count: number;
  limit: number;
  offset: number;
};

export type BatchGenerateNameResponse = {
  ok_count: number;
  persisted_count: number;
  skipped_locked_count: number;
  skipped_idempotent_count: number;
  errors: { product_id: number; reason: string }[];
};

export type OdooPushResponse = {
  total: number;
  pushed: number;
  skipped: number;
  errors: number;
};

export type SyncOdooResponse = {
  dry_run: boolean;
  total: number;
  pushed: number;
  skipped_locked: number;
  skipped_idempotent: number;
  skipped_invalid: number;
  errors: number;
  synced_product_ids: number[];
  log: { product_id: number; action: string; detail: string }[];
};

export async function fetchProductCatalogPage(
  offset: number,
  limit: number,
  filters: CatalogQueryFilters = {},
): Promise<ProductCatalogPage> {
  const qs = new URLSearchParams({
    offset: String(offset),
    limit: String(limit),
  });
  const search = filters.search?.trim();
  if (search) {
    qs.set("search", search);
  }
  if (filters.naming_status) {
    qs.set("naming_status", filters.naming_status);
  }
  if (filters.is_locked !== undefined) {
    qs.set("is_locked", String(filters.is_locked));
  }
  if (filters.has_error !== undefined) {
    qs.set("has_error", String(filters.has_error));
  }
  const res = await fetch(`/api/products?${qs}`);
  if (!res.ok) {
    throw new Error(`Ошибка загрузки каталога: HTTP ${res.status}`);
  }
  return res.json() as Promise<ProductCatalogPage>;
}

export async function batchGenerateNames(
  productIds: number[],
): Promise<BatchGenerateNameResponse> {
  const res = await fetch("/api/products/batch/generate-name", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ product_ids: productIds }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `HTTP ${res.status}`);
  }
  return res.json() as Promise<BatchGenerateNameResponse>;
}

export async function syncProductsToOdoo(
  productIds: number[],
): Promise<SyncOdooResponse> {
  const res = await fetch("/api/sync/odoo", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ product_ids: productIds }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `HTTP ${res.status}`);
  }
  return res.json() as Promise<SyncOdooResponse>;
}

export type SaveProductFitmentPayload = {
  make_id: number;
  model_id: number;
  generation_id: number;
};

export type ProductManualOverridePayload = {
  manual_name?: string;
  is_locked?: boolean;
};

export async function patchProductManualOverride(
  productId: number,
  payload: ProductManualOverridePayload,
): Promise<ProductCatalogItem> {
  const res = await fetch(`/api/products/${productId}/override`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `HTTP ${res.status}`);
  }
  const data = (await res.json()) as { product: ProductCatalogItem };
  return data.product;
}

export async function saveProductFitment(
  productId: number,
  payload: SaveProductFitmentPayload,
): Promise<ProductCatalogItem> {
  const res = await fetch(`/api/products/${productId}/fitment`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `HTTP ${res.status}`);
  }
  const data = (await res.json()) as { product: ProductCatalogItem };
  return data.product;
}

/** @deprecated Use syncProductsToOdoo */
export async function pushProductsToOdoo(
  productIds: number[],
): Promise<OdooPushResponse> {
  const res = await syncProductsToOdoo(productIds);
  return {
    total: res.total,
    pushed: res.pushed,
    skipped: res.skipped_locked + res.skipped_idempotent + res.skipped_invalid,
    errors: res.errors,
  };
}
