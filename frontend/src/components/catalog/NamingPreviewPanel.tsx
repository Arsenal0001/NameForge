import { Loader2, Sparkles, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type { NamingPreviewResponse } from "@/lib/naming-api";
import type { ProductCatalogItem } from "@/lib/catalog-api";
import { cn } from "@/lib/utils";

type NamingPreviewPanelProps = {
  item: ProductCatalogItem;
  preview: NamingPreviewResponse | null;
  isPending: boolean;
  errorMessage: string | null;
  onClose: () => void;
};

function LongBlock({
  label,
  value,
  className,
}: {
  label: string;
  value: string;
  className?: string;
}) {
  const text = value.trim() || "—";
  return (
    <div className="space-y-1">
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      {text === "—" ? (
        <p className="text-sm text-muted-foreground">—</p>
      ) : (
        <Tooltip>
          <TooltipTrigger asChild>
            <p
              className={cn(
                "cursor-help text-sm leading-relaxed break-words line-clamp-4",
                className,
              )}
            >
              {text}
            </p>
          </TooltipTrigger>
          <TooltipContent
            side="left"
            align="start"
            className="max-w-md whitespace-pre-wrap break-words"
          >
            {text}
          </TooltipContent>
        </Tooltip>
      )}
    </div>
  );
}

export function NamingPreviewPanel({
  item,
  preview,
  isPending,
  errorMessage,
  onClose,
}: NamingPreviewPanelProps) {
  return (
    <aside
      className="flex w-[min(420px,100vw)] shrink-0 flex-col border-l border-border bg-card shadow-lg"
      aria-label="Превью генерации имени"
    >
      <div className="flex items-start justify-between gap-3 border-b border-border px-4 py-3">
        <div className="min-w-0">
          <h2 className="text-base font-semibold text-foreground">
            Превью имени
          </h2>
          <p className="mt-0.5 truncate font-mono text-xs text-muted-foreground">
            {item.article || `id:${item.id}`}
          </p>
        </div>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="h-8 w-8 shrink-0"
          onClick={onClose}
          aria-label="Закрыть панель превью"
        >
          <X className="h-4 w-4" />
        </Button>
      </div>

      <div className="flex flex-1 flex-col gap-4 overflow-y-auto p-4">
        {isPending ? (
          <div className="flex flex-col items-center justify-center gap-3 py-16 text-muted-foreground">
            <Loader2 className="h-8 w-8 animate-spin" />
            <p className="text-sm">Генерация превью…</p>
          </div>
        ) : errorMessage ? (
          <div className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
            {errorMessage}
          </div>
        ) : preview ? (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <Badge
                variant={
                  preview.status === "error"
                    ? "destructive"
                    : preview.status === "review"
                      ? "secondary"
                      : "outline"
                }
              >
                {preview.status === "generated"
                  ? "готово"
                  : preview.status === "review"
                    ? "на проверку"
                    : "ошибка"}
              </Badge>
              {preview.changed ? (
                <Badge variant="outline" className="border-emerald-500/40 text-emerald-700">
                  имя изменится
                </Badge>
              ) : preview.current_name ? (
                <Badge variant="outline">без изменений</Badge>
              ) : null}
              {preview.truncated ? (
                <Badge variant="secondary">обрезано до 255</Badge>
              ) : null}
            </div>

            <div className="space-y-3 rounded-lg border border-border bg-muted/30 p-3">
              <LongBlock
                label="Текущее имя (Odoo)"
                value={preview.current_name}
                className="text-muted-foreground line-through decoration-muted-foreground/60"
              />
              <div className="relative">
                <div className="absolute -left-1 top-0 bottom-0 w-0.5 rounded-full bg-emerald-500" />
                <LongBlock
                  label="Новое каноническое имя"
                  value={preview.name}
                  className="pl-3 font-medium text-emerald-800 dark:text-emerald-300"
                />
              </div>
            </div>

            <LongBlock
              label="Ключевые слова для поиска"
              value={preview.search_keywords}
            />

            {preview.description ? (
              <LongBlock label="Описание" value={preview.description} />
            ) : null}

            {preview.warnings.length > 0 ? (
              <div className="space-y-1">
                <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Предупреждения
                </p>
                <ul className="list-inside list-disc text-sm text-amber-800 dark:text-amber-200">
                  {preview.warnings.map((w) => (
                    <li key={w}>{w}</li>
                  ))}
                </ul>
              </div>
            ) : null}

            {preview.missing_fields.length > 0 ? (
              <div className="space-y-1">
                <p className=" text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Не хватает полей
                </p>
                <ul className="list-inside list-disc text-sm text-destructive">
                  {preview.missing_fields.map((f) => (
                    <li key={f}>{f}</li>
                  ))}
                </ul>
              </div>
            ) : null}
          </>
        ) : (
          <div className="flex flex-col items-center gap-2 py-16 text-center text-muted-foreground">
            <Sparkles className="h-8 w-8 opacity-40" />
            <p className="text-sm">
              Нажмите «Сгенерировать превью» в строке каталога.
            </p>
          </div>
        )}
      </div>
    </aside>
  );
}
