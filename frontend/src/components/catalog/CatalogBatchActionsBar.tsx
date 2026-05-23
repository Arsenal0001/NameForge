import { Loader2, CloudUpload } from "lucide-react";

import { Button } from "@/components/ui/button";

type CatalogBatchActionsBarProps = {
  selectedCount: number;
  isSyncPending: boolean;
  isGeneratePending: boolean;
  onSync: () => void;
  onGenerate: () => void;
};

export function CatalogBatchActionsBar({
  selectedCount,
  isSyncPending,
  isGeneratePending,
  onSync,
  onGenerate,
}: CatalogBatchActionsBarProps) {
  if (selectedCount <= 0) {
    return null;
  }

  const busy = isSyncPending || isGeneratePending;

  return (
    <div
      className="sticky bottom-4 z-20 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-card/95 px-4 py-3 shadow-lg backdrop-blur supports-[backdrop-filter]:bg-card/80"
      role="region"
      aria-label="Пакетные действия"
    >
      <p className="text-sm font-medium text-foreground">
        Выбрано: {selectedCount}
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          variant="outline"
          disabled={busy}
          onClick={onGenerate}
        >
          {isGeneratePending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : null}
          Сгенерировать названия
        </Button>
        <Button size="sm" disabled={busy} onClick={onSync}>
          {isSyncPending ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <CloudUpload className="mr-2 h-4 w-4" />
          )}
          Отправить в Odoo
        </Button>
      </div>
    </div>
  );
}
