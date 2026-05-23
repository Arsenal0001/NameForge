export type NamingMatrixOption = {
  matrix_id: string;
  title: string;
  formula_hint: string;
};

export type CategoryRow = {
  odoo_id: number;
  name: string;
  complete_name: string | null;
  parent_id: number | null;
  naming_template_key: string | null;
  name_pattern: string | null;
};

export type CategoryListPage = {
  items: CategoryRow[];
  total_count: number;
  limit: number;
  offset: number;
};

export async function fetchNamingMatrices(): Promise<NamingMatrixOption[]> {
  const res = await fetch("/api/categories/matrices");
  if (!res.ok) {
    throw new Error(`Матрицы: HTTP ${res.status}`);
  }
  return res.json() as Promise<NamingMatrixOption[]>;
}

export async function fetchCategoriesPage(
  q: string,
  offset: number,
  limit: number,
): Promise<CategoryListPage> {
  const qs = new URLSearchParams({
    offset: String(offset),
    limit: String(limit),
  });
  const trimmed = q.trim();
  if (trimmed) {
    qs.set("q", trimmed);
  }
  const res = await fetch(`/api/categories?${qs}`);
  if (!res.ok) {
    throw new Error(`Категории: HTTP ${res.status}`);
  }
  return res.json() as Promise<CategoryListPage>;
}

export async function putCategoryTemplate(
  odooId: number,
  namingTemplateKey: string | null,
): Promise<CategoryRow> {
  const res = await fetch(`/api/categories/${odooId}/template`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ naming_template_key: namingTemplateKey }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `HTTP ${res.status}`);
  }
  return res.json() as Promise<CategoryRow>;
}
