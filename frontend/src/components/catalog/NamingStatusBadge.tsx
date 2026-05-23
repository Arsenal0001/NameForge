import { Badge } from "@/components/ui/badge";
import type { NamingStatus } from "@/lib/catalog-api";

const STATUS_LABELS: Record<NamingStatus, string> = {
  no_template: "Нет шаблона",
  pending_sync: "Ожидает отправки",
  synced: "В Odoo",
};

type NamingStatusBadgeProps = {
  status: NamingStatus;
};

export function NamingStatusBadge({ status }: NamingStatusBadgeProps) {
  switch (status) {
    case "no_template":
      return (
        <Badge variant="destructive" className="shrink-0 text-[10px] font-normal">
          🔴 {STATUS_LABELS.no_template}
        </Badge>
      );
    case "pending_sync":
      return (
        <Badge
          variant="secondary"
          className="shrink-0 border-amber-500/40 bg-amber-50 text-[10px] font-normal text-amber-900 dark:bg-amber-950/40 dark:text-amber-100"
        >
          🟡 {STATUS_LABELS.pending_sync}
        </Badge>
      );
    case "synced":
      return (
        <Badge
          variant="outline"
          className="shrink-0 border-emerald-500/40 text-[10px] font-normal text-emerald-800 dark:text-emerald-300"
        >
          🟢 {STATUS_LABELS.synced}
        </Badge>
      );
    default:
      return null;
  }
}
