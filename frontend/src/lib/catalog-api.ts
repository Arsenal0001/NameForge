export type ProductCatalogItem = {
  id: number;
  article: string;
  name: string;
  category: string;
  brand: string;
  name_locked: boolean;
  category_template_bound: boolean;
  search_keywords: string;
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

export async function fetchProductCatalogPage(
  offset: number,
  limit: number,
): Promise<ProductCatalogPage> {
  const qs = new URLSearchParams({
    offset: String(offset),
    limit: String(limit),
  });
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

export async function pushProductsToOdoo(
  productIds: number[],
): Promise<OdooPushResponse> {
  const res = await fetch("/api/odoo/push", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ product_ids: productIds }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `HTTP ${res.status}`);
  }
  return res.json() as Promise<OdooPushResponse>;
}
