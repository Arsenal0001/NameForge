export type NamingPreviewRequest = {
  part_type: string;
  brand?: string;
  article?: string;
  applicability_type?: "fitment" | "universal";
  primary_make?: string | null;
  primary_model?: string | null;
  primary_body?: string | null;
  year_from?: number | null;
  year_to?: number | null;
  engine?: string | null;
  side_axis?: string | null;
  cross_numbers?: string | null;
  characteristic_parts?: string[];
  installation_location?: string | null;
  supplier_raw_name?: string | null;
  template_pattern?: string | null;
  current_name?: string | null;
};

export type NamingPreviewResponse = {
  current_name: string;
  name: string;
  search_keywords: string;
  description: string;
  status: "generated" | "review" | "error";
  warnings: string[];
  missing_fields: string[];
  template_pattern_used: string | null;
  truncated: boolean;
  changed: boolean;
};

export async function previewNaming(
  payload: NamingPreviewRequest,
): Promise<NamingPreviewResponse> {
  const res = await fetch("/api/naming/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `HTTP ${res.status}`);
  }
  return res.json() as Promise<NamingPreviewResponse>;
}

export function catalogItemToPreviewRequest(item: {
  name: string;
  article: string;
  brand: string;
  category: string;
  part_type?: string;
  applicability_type?: string;
  primary_make?: string;
  primary_model?: string;
  fitment_summary?: string;
}): NamingPreviewRequest {
  const partType = (item.part_type || item.category || "").trim();
  const applRaw = (item.applicability_type || "").trim().toLowerCase();
  const hasPrimary =
    Boolean(item.primary_make?.trim()) || Boolean(item.primary_model?.trim());
  const applicability_type: "fitment" | "universal" =
    applRaw === "fitment" || hasPrimary ? "fitment" : "universal";

  const characteristic_parts: string[] = [];
  const summary = (item.fitment_summary || "").trim();
  if (summary) {
    characteristic_parts.push(summary);
  }

  return {
    part_type: partType || "Запчасть",
    brand: item.brand || "",
    article: item.article || "",
    applicability_type,
    primary_make: item.primary_make?.trim() || null,
    primary_model: item.primary_model?.trim() || null,
    characteristic_parts,
    supplier_raw_name: item.name?.trim() || null,
    current_name: item.name?.trim() || null,
  };
}
