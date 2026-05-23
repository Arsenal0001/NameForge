import { useEffect, useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";

import {
  HierarchicalFitmentSelect,
  type FitmentSelection,
} from "@/components/HierarchicalFitmentSelect";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Switch } from "@/components/ui/switch";
import {
  patchProductManualOverride,
  saveProductFitment,
  type ProductCatalogItem,
  type ProductCatalogPage,
} from "@/lib/catalog-api";

const EMPTY_FITMENT: FitmentSelection = {
  makeId: null,
  modelId: null,
  generationId: null,
};

type FitmentEditorSheetProps = {
  open: boolean;
  product: ProductCatalogItem | null;
  fitment: FitmentSelection;
  onFitmentChange: (value: FitmentSelection) => void;
  onOpenChange: (open: boolean) => void;
  catalogQueryKey: readonly unknown[];
};

function productDisplayName(item: ProductCatalogItem): string {
  return (
    String(item.odoo_name || item.name || item.part_type || "").trim() ||
    `Товар #${item.id}`
  );
}

function defaultManualName(item: ProductCatalogItem): string {
  return String(item.preview_name || item.name || "").trim();
}

function updateCatalogItem(
  queryClient: ReturnType<typeof useQueryClient>,
  catalogQueryKey: readonly unknown[],
  updated: ProductCatalogItem,
) {
  queryClient.setQueryData<ProductCatalogPage>(catalogQueryKey, (old) => {
    if (!old) {
      return old;
    }
    return {
      ...old,
      items: old.items.map((item) => (item.id === updated.id ? updated : item)),
    };
  });
}

export function FitmentEditorSheet({
  open,
  product,
  fitment,
  onFitmentChange,
  onOpenChange,
  catalogQueryKey,
}: FitmentEditorSheetProps) {
  const queryClient = useQueryClient();
  const [isLocked, setIsLocked] = useState(false);
  const [manualName, setManualName] = useState("");
  const [initialLocked, setInitialLocked] = useState(false);
  const [initialManualName, setInitialManualName] = useState("");

  useEffect(() => {
    if (!product || !open) {
      return;
    }
    const locked = Boolean(product.name_locked);
    const manual = defaultManualName(product);
    setIsLocked(locked);
    setManualName(manual);
    setInitialLocked(locked);
    setInitialManualName(manual);
  }, [product, open]);

  const overrideDirty = useMemo(() => {
    if (!product) {
      return false;
    }
    if (isLocked !== initialLocked) {
      return true;
    }
    if (isLocked && manualName.trim() !== initialManualName.trim()) {
      return true;
    }
    return false;
  }, [product, isLocked, initialLocked, manualName, initialManualName]);

  const fitmentReady =
    product != null &&
    fitment.makeId != null &&
    fitment.modelId != null &&
    fitment.generationId != null;

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (!product) {
        throw new Error("Товар не выбран");
      }

      let latest = product;

      if (overrideDirty) {
        if (isLocked && !manualName.trim()) {
          throw new Error("Укажите имя для ручной фиксации");
        }

        const previousPage = queryClient.getQueryData<ProductCatalogPage>(
          catalogQueryKey,
        );
        const optimistic: ProductCatalogItem = {
          ...product,
          name_locked: isLocked,
          preview_name: isLocked ? manualName.trim() : product.preview_name,
          name: isLocked ? manualName.trim() : product.name,
          last_sync_error: null,
        };
        updateCatalogItem(queryClient, catalogQueryKey, optimistic);

        try {
          latest = await patchProductManualOverride(product.id, {
            is_locked: isLocked,
            ...(isLocked ? { manual_name: manualName.trim() } : {}),
          });
          updateCatalogItem(queryClient, catalogQueryKey, latest);
        } catch (error) {
          if (previousPage) {
            queryClient.setQueryData(catalogQueryKey, previousPage);
          }
          throw error;
        }
      }

      if (fitmentReady) {
        latest = await saveProductFitment(product.id, {
          make_id: fitment.makeId!,
          model_id: fitment.modelId!,
          generation_id: fitment.generationId!,
        });
        updateCatalogItem(queryClient, catalogQueryKey, latest);
      }

      return latest;
    },
    onSuccess: (updated) => {
      const locked = Boolean(updated.name_locked);
      const manual = defaultManualName(updated);
      setIsLocked(locked);
      setManualName(manual);
      setInitialLocked(locked);
      setInitialManualName(manual);

      toast.success("Карточка товара сохранена", {
        description: updated.preview_name
          ? `Имя: ${updated.preview_name}`
          : undefined,
      });
      onOpenChange(false);
    },
    onError: (error: unknown) => {
      toast.error(
        error instanceof Error ? error.message : "Не удалось сохранить карточку",
      );
    },
  });

  const canSave =
    product != null &&
    (overrideDirty || fitmentReady) &&
    !saveMutation.isPending &&
    (!isLocked || manualName.trim().length > 0);

  const previewLabel = product
    ? String(product.preview_name || product.name || "").trim()
    : "";

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="flex w-full flex-col sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>Карточка товара</SheetTitle>
          {product ? (
            <>
              <p className="text-sm font-medium leading-snug text-foreground">
                {productDisplayName(product)}
              </p>
              <SheetDescription className="font-mono text-xs">
                {product.article?.trim()
                  ? `Артикул: ${product.article.trim()}`
                  : `Код: id:${product.id}`}
              </SheetDescription>
            </>
          ) : (
            <SheetDescription>Выберите товар в таблице каталога.</SheetDescription>
          )}
        </SheetHeader>

        <div className="flex-1 space-y-6 overflow-y-auto py-2">
          <section className="space-y-3 rounded-lg border border-border p-4">
            <div className="flex items-center justify-between gap-3">
              <Label htmlFor="manual-name-lock" className="text-sm font-medium">
                Ручная фиксация имени (Lock)
              </Label>
              <Switch
                id="manual-name-lock"
                checked={isLocked}
                onCheckedChange={(checked) => {
                  setIsLocked(checked);
                  if (checked && !manualName.trim() && product) {
                    setManualName(defaultManualName(product));
                  }
                }}
                disabled={!product || saveMutation.isPending}
              />
            </div>
            {isLocked ? (
              <div className="space-y-2">
                <Label htmlFor="manual-name-input">Имя для Odoo</Label>
                <Input
                  id="manual-name-input"
                  value={manualName}
                  onChange={(event) => setManualName(event.target.value)}
                  disabled={!product || saveMutation.isPending}
                  maxLength={255}
                  placeholder="Введите фиксированное наименование…"
                />
                <p className="text-xs text-muted-foreground">
                  Naming Engine не будет перезаписывать это имя при обогащении и
                  webhook-событиях. Изменения можно отправить в Odoo через sync.
                </p>
              </div>
            ) : (
              <div className="space-y-1">
                <p className="text-xs font-medium text-muted-foreground">
                  Превью Naming Engine
                </p>
                <p className="text-sm leading-snug text-foreground">
                  {previewLabel || "—"}
                </p>
              </div>
            )}
          </section>

          <section className="space-y-3">
            <h3 className="text-sm font-medium text-foreground">Применимость</h3>
            <HierarchicalFitmentSelect
              value={fitment}
              onChange={onFitmentChange}
              disabled={!product || saveMutation.isPending}
              className="sm:grid-cols-1"
            />
          </section>
        </div>

        <SheetFooter>
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={saveMutation.isPending}
          >
            Отмена
          </Button>
          <Button
            type="button"
            onClick={() => saveMutation.mutate()}
            disabled={!canSave}
          >
            {saveMutation.isPending ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                Сохранение…
              </>
            ) : (
              "Сохранить"
            )}
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}

export { EMPTY_FITMENT };
