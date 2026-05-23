import type { CategoryRow } from "@/lib/categories-api";

export type CategoryTemplateRow = {
  category_id: number;
  category_name: string;
  complete_name: string | null;
  name_pattern: string;
};

export type TemplateTokenHint = {
  token: string;
  description: string;
};

export type TemplateLivePreviewItem = {
  odoo_id: number | null;
  odoo_name: string;
  generated_name: string;
  status: string;
  warnings: string[];
};

export type TemplateLivePreviewResponse = {
  category_id: number;
  template_string: string;
  normalized_pattern: string;
  items: TemplateLivePreviewItem[];
  sample_source: string;
};

export async function fetchTemplateTokens(): Promise<TemplateTokenHint[]> {
  const res = await fetch("/api/templates/tokens");
  if (!res.ok) {
    throw new Error(`Токены: HTTP ${res.status}`);
  }
  const data = (await res.json()) as { tokens: TemplateTokenHint[] };
  return data.tokens;
}

export async function fetchCategoryTemplate(
  categoryId: number,
): Promise<CategoryTemplateRow | null> {
  const res = await fetch(`/api/templates/${categoryId}`);
  if (res.status === 404) {
    return null;
  }
  if (!res.ok) {
    throw new Error(`Шаблон: HTTP ${res.status}`);
  }
  return res.json() as Promise<CategoryTemplateRow>;
}

export async function saveCategoryTemplate(
  categoryId: number,
  namePattern: string,
): Promise<CategoryTemplateRow> {
  const res = await fetch(`/api/templates/${categoryId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name_pattern: namePattern }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `HTTP ${res.status}`);
  }
  return res.json() as Promise<CategoryTemplateRow>;
}

export async function deleteCategoryTemplate(categoryId: number): Promise<void> {
  const res = await fetch(`/api/templates/${categoryId}`, { method: "DELETE" });
  if (!res.ok && res.status !== 404) {
    throw new Error(`HTTP ${res.status}`);
  }
}

export async function previewLiveTemplate(
  categoryId: number,
  templateString: string,
): Promise<TemplateLivePreviewResponse> {
  const res = await fetch("/api/templates/preview-live", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      category_id: categoryId,
      template_string: templateString,
    }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `HTTP ${res.status}`);
  }
  return res.json() as Promise<TemplateLivePreviewResponse>;
}

export function categoryLabel(row: CategoryRow): string {
  return (row.complete_name || row.name || "").trim() || `id ${row.odoo_id}`;
}
