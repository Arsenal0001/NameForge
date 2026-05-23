import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  CheckCircle2,
  Clock3,
  Database,
  Download,
  Loader2,
  Lock,
  Sparkles,
  UploadCloud,
  type LucideIcon,
} from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { fetchDashboardMetrics } from "@/lib/metrics-api";
import {
  type CatalogJobKind,
  fetchActiveJobs,
  JOB_TYPE_LABELS,
  type JobProgressItem,
  triggerCatalogJob,
} from "@/lib/jobs-api";
import { cn } from "@/lib/utils";

const METRICS_REFETCH_INTERVAL_MS = 45_000;
const JOBS_POLL_INTERVAL_MS = 4_000;

const JOB_STARTED_TOAST =
  "Задача запущена в фоне. Прогресс отображается ниже.";

type QuickActionConfig = {
  kind: CatalogJobKind;
  label: string;
  icon: LucideIcon;
  variant?: "default" | "outline";
};

const QUICK_ACTIONS: QuickActionConfig[] = [
  {
    kind: "sync-from-odoo",
    label: "Скачать из Odoo",
    icon: Download,
    variant: "outline",
  },
  {
    kind: "enrich",
    label: "Обогатить из JSONL",
    icon: Sparkles,
    variant: "outline",
  },
  {
    kind: "push-to-odoo",
    label: "Массовая отправка в Odoo",
    icon: UploadCloud,
  },
];

type MetricCardConfig = {
  key: keyof Awaited<ReturnType<typeof fetchDashboardMetrics>>;
  title: string;
  icon: LucideIcon;
  iconClassName: string;
};

const METRIC_CARDS: MetricCardConfig[] = [
  {
    key: "total_products",
    title: "Всего товаров",
    icon: Database,
    iconClassName: "text-blue-600",
  },
  {
    key: "synced",
    title: "Синхронизировано",
    icon: CheckCircle2,
    iconClassName: "text-emerald-600",
  },
  {
    key: "pending",
    title: "Ожидают отправки",
    icon: Clock3,
    iconClassName: "text-amber-600",
  },
  {
    key: "locked",
    title: "Заблокировано",
    icon: Lock,
    iconClassName: "text-violet-600",
  },
];

function formatMetricValue(value: number): string {
  return value.toLocaleString("ru-RU");
}

function formatProgressLine(job: JobProgressItem): string {
  if (job.total_items > 0) {
    return `Обработано: ${job.processed_items.toLocaleString("ru-RU")} из ${job.total_items.toLocaleString("ru-RU")}`;
  }
  return `Обработано: ${job.processed_items.toLocaleString("ru-RU")}`;
}

function jobStatusLabel(status: JobProgressItem["status"]): string {
  switch (status) {
    case "running":
      return "Выполняется";
    case "completed":
      return "Завершено";
    case "failed":
      return "Ошибка";
  }
}

function MetricCardSkeleton() {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <Skeleton className="h-4 w-28" />
        <Skeleton className="h-5 w-5 rounded-full" />
      </CardHeader>
      <CardContent>
        <Skeleton className="h-9 w-24" />
      </CardContent>
    </Card>
  );
}

type MetricCardProps = {
  title: string;
  value: number;
  icon: LucideIcon;
  iconClassName: string;
};

function MetricCard({ title, value, icon: Icon, iconClassName }: MetricCardProps) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle>{title}</CardTitle>
        <Icon className={cn("h-5 w-5", iconClassName)} aria-hidden />
      </CardHeader>
      <CardContent>
        <p className="text-3xl font-semibold tracking-tight tabular-nums">
          {formatMetricValue(value)}
        </p>
      </CardContent>
    </Card>
  );
}

function ActiveJobCard({ job }: { job: JobProgressItem }) {
  const title = JOB_TYPE_LABELS[job.job_type] ?? job.job_type;
  const statusLabel = jobStatusLabel(job.status);

  return (
    <div
      className={cn(
        "rounded-lg border p-4",
        job.status === "failed" && "border-destructive/40 bg-destructive/5",
      )}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-medium text-foreground">{title}</p>
        <span
          className={cn(
            "text-xs font-medium uppercase tracking-wide",
            job.status === "running" && "text-primary",
            job.status === "completed" && "text-emerald-600",
            job.status === "failed" && "text-destructive",
          )}
        >
          {statusLabel}
        </span>
      </div>
      <p className="mt-1 text-sm text-muted-foreground tabular-nums">
        {formatProgressLine(job)}
      </p>
      {job.status !== "failed" ? (
        <Progress className="mt-3" value={job.progress_percent} />
      ) : null}
      {job.status === "failed" && job.error_message ? (
        <div className="mt-3 flex gap-2 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          <p className="break-words">{job.error_message}</p>
        </div>
      ) : null}
    </div>
  );
}

export function MainDashboard() {
  const queryClient = useQueryClient();
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["dashboard-metrics"],
    queryFn: fetchDashboardMetrics,
    refetchInterval: METRICS_REFETCH_INTERVAL_MS,
  });

  const {
    data: activeJobsData,
    isLoading: jobsLoading,
    isError: jobsError,
  } = useQuery({
    queryKey: ["active-jobs"],
    queryFn: fetchActiveJobs,
    refetchInterval: JOBS_POLL_INTERVAL_MS,
  });

  const visibleJobs =
    activeJobsData?.jobs.filter(
      (job) =>
        job.status === "running" ||
        job.status === "failed" ||
        job.status === "completed",
    ) ?? [];

  const jobMutation = useMutation({
    mutationFn: triggerCatalogJob,
    onSuccess: () => {
      toast.success(JOB_STARTED_TOAST);
      void queryClient.invalidateQueries({ queryKey: ["dashboard-metrics"] });
      void queryClient.invalidateQueries({ queryKey: ["active-jobs"] });
    },
    onError: (mutationError: Error) => {
      toast.error(mutationError.message || "Не удалось запустить задачу.");
    },
  });

  const pendingJob = jobMutation.isPending ? jobMutation.variables : null;
  const hasRunningJob = visibleJobs.some((job) => job.status === "running");

  return (
    <div className="flex flex-1 flex-col gap-6 p-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">
          Главный дашборд
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Состояние локального каталога и очереди синхронизации с Odoo. Метрики
          обновляются каждые 45 секунд; прогресс фоновых задач — каждые 4 секунды.
        </p>
      </div>

      {isError ? (
        <div className="rounded-md border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm text-destructive">
          {(error as Error).message || "Не удалось загрузить метрики дашборда."}
        </div>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {isLoading || !data
          ? METRIC_CARDS.map((card) => <MetricCardSkeleton key={card.key} />)
          : METRIC_CARDS.map((card) => (
              <MetricCard
                key={card.key}
                title={card.title}
                value={data[card.key]}
                icon={card.icon}
                iconClassName={card.iconClassName}
              />
            ))}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Управление каталогом</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            Запуск ETL-операций в фоне. Пока задача выполняется, повторный запуск
            того же действия будет отклонён.
          </p>
          <div className="flex flex-wrap gap-3">
            {QUICK_ACTIONS.map((action) => {
              const Icon = action.icon;
              const isBusy = pendingJob === action.kind;
              return (
                <Button
                  key={action.kind}
                  variant={action.variant ?? "default"}
                  disabled={jobMutation.isPending}
                  onClick={() => jobMutation.mutate(action.kind)}
                >
                  {isBusy ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Icon className="h-4 w-4" />
                  )}
                  {action.label}
                </Button>
              );
            })}
          </div>

          {jobsError ? (
            <div className="rounded-md border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm text-destructive">
              Не удалось загрузить статус фоновых задач.
            </div>
          ) : null}

          {jobsLoading && !activeJobsData ? (
            <Skeleton className="h-24 w-full" />
          ) : null}

          {visibleJobs.length > 0 ? (
            <div className="space-y-3">
              <div className="flex items-center gap-2 text-sm font-medium text-foreground">
                {hasRunningJob ? (
                  <Loader2 className="h-4 w-4 animate-spin text-primary" />
                ) : null}
                Фоновые задачи
              </div>
              {visibleJobs.map((job) => (
                <ActiveJobCard key={`${job.job_type}-${job.started_at}`} job={job} />
              ))}
            </div>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}
