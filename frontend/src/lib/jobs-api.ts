export type JobAcceptedResponse = {
  job: string;
  status: "accepted";
  message: string;
};

export type JobRunStatus = "running" | "completed" | "failed";

export type JobProgressItem = {
  job_type: string;
  status: JobRunStatus;
  processed_items: number;
  total_items: number;
  progress_percent: number;
  error_message: string | null;
  started_at: string | null;
  finished_at: string | null;
};

export type ActiveJobsResponse = {
  jobs: JobProgressItem[];
};

export type CatalogJobKind =
  | "sync-from-odoo"
  | "enrich"
  | "push-to-odoo";

const JOB_ENDPOINTS: Record<CatalogJobKind, string> = {
  "sync-from-odoo": "/api/jobs/sync-from-odoo",
  enrich: "/api/jobs/enrich",
  "push-to-odoo": "/api/jobs/push-to-odoo",
};

export const JOB_TYPE_LABELS: Record<string, string> = {
  sync_from_odoo: "Скачивание из Odoo",
  enrich: "Обогащение из JSONL",
  push_to_odoo: "Массовая отправка в Odoo",
};

export async function fetchActiveJobs(): Promise<ActiveJobsResponse> {
  const res = await fetch("/api/jobs/active");
  if (!res.ok) {
    throw new Error(`Ошибка загрузки задач: HTTP ${res.status}`);
  }
  return res.json() as Promise<ActiveJobsResponse>;
}

export async function triggerCatalogJob(
  kind: CatalogJobKind,
): Promise<JobAcceptedResponse> {
  const res = await fetch(JOB_ENDPOINTS[kind], { method: "POST" });
  if (res.status === 409) {
    throw new Error("Задача уже выполняется. Дождитесь завершения.");
  }
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `HTTP ${res.status}`);
  }
  return res.json() as Promise<JobAcceptedResponse>;
}
