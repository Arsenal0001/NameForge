export type DashboardMetrics = {
  total_products: number;
  synced: number;
  pending: number;
  locked: number;
};

export async function fetchDashboardMetrics(): Promise<DashboardMetrics> {
  const res = await fetch("/api/metrics/dashboard");
  if (!res.ok) {
    throw new Error(`Ошибка загрузки метрик: HTTP ${res.status}`);
  }
  return res.json() as Promise<DashboardMetrics>;
}
