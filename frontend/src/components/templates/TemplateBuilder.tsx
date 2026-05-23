import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Save, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { SmartCategoryCombobox } from "@/components/templates/SmartCategoryCombobox";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { fetchCategoriesPage, type CategoryRow } from "@/lib/categories-api";
import {
  deleteCategoryTemplate,
  fetchCategoryTemplate,
  fetchTemplateTokens,
  previewLiveTemplate,
  saveCategoryTemplate,
} from "@/lib/templates-api";

const DEFAULT_PATTERN = "{part_type} {brand} {make} {model}";
const PREVIEW_DEBOUNCE_MS = 400;

export function TemplateBuilder() {
  const queryClient = useQueryClient();
  const [selectedCategory, setSelectedCategory] = useState<CategoryRow | null>(
    null,
  );
  const [templateString, setTemplateString] = useState(DEFAULT_PATTERN);
  const debouncedTemplate = useDebouncedValue(templateString, PREVIEW_DEBOUNCE_MS);

  const categoriesQuery = useQuery({
    queryKey: ["categories-all"],
    queryFn: () => fetchCategoriesPage("", 0, 500),
    staleTime: 60_000,
  });

  const tokensQuery = useQuery({
    queryKey: ["template-tokens"],
    queryFn: fetchTemplateTokens,
    staleTime: Infinity,
  });

  const savedTemplateQuery = useQuery({
    queryKey: ["category-template", selectedCategory?.odoo_id],
    queryFn: () => fetchCategoryTemplate(selectedCategory!.odoo_id),
    enabled: selectedCategory != null,
  });

  const handleCategoryChange = (row: CategoryRow | null) => {
    setSelectedCategory(row);
    if (row?.name_pattern) {
      setTemplateString(row.name_pattern);
    } else if (row === null) {
      setTemplateString(DEFAULT_PATTERN);
    }
  };

  useEffect(() => {
    if (savedTemplateQuery.data?.name_pattern) {
      setTemplateString(savedTemplateQuery.data.name_pattern);
    } else if (
      selectedCategory != null &&
      !savedTemplateQuery.isLoading &&
      !selectedCategory.name_pattern
    ) {
      setTemplateString(DEFAULT_PATTERN);
    }
  }, [
    savedTemplateQuery.data,
    savedTemplateQuery.isLoading,
    selectedCategory,
  ]);

  const previewQuery = useQuery({
    queryKey: [
      "template-preview-live",
      selectedCategory?.odoo_id,
      debouncedTemplate,
    ],
    queryFn: () =>
      previewLiveTemplate(selectedCategory!.odoo_id, debouncedTemplate),
    enabled:
      selectedCategory != null && debouncedTemplate.trim().length > 0,
    staleTime: 0,
    retry: 0,
  });

  const saveMutation = useMutation({
    mutationFn: () =>
      saveCategoryTemplate(selectedCategory!.odoo_id, templateString.trim()),
    onSuccess: () => {
      toast.success("Шаблон сохранён локально");
      void queryClient.invalidateQueries({ queryKey: ["category-template"] });
      void queryClient.invalidateQueries({ queryKey: ["products"] });
    },
    onError: (e: unknown) => {
      toast.error(e instanceof Error ? e.message : "Ошибка сохранения");
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () => deleteCategoryTemplate(selectedCategory!.odoo_id),
    onSuccess: () => {
      toast.success("Привязка шаблона удалена");
      setTemplateString(DEFAULT_PATTERN);
      void queryClient.invalidateQueries({ queryKey: ["category-template"] });
    },
    onError: (e: unknown) => {
      toast.error(e instanceof Error ? e.message : "Ошибка удаления");
    },
  });

  const previewLoading =
    previewQuery.isFetching &&
    debouncedTemplate !== templateString
      ? false
      : previewQuery.isFetching;

  return (
    <div className="flex flex-1 flex-col gap-6 p-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">
          Управление шаблонами
        </h1>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
          Привяжите формулу имени к категории Odoo и проверьте превью на реальных
          товарах. Запись в Odoo не выполняется — только локальное сохранение и
          read-only выборка для превью.
        </p>
      </div>

      <div className="flex max-w-xl flex-col gap-2">
        <Label>Категория Odoo</Label>
        <SmartCategoryCombobox
          categories={categoriesQuery.data?.items ?? []}
          value={selectedCategory}
          onChange={handleCategoryChange}
          loading={categoriesQuery.isLoading}
          disabled={categoriesQuery.isError}
        />
        {categoriesQuery.isError ? (
          <p className="text-sm text-destructive">
            Не удалось загрузить категории. Выполните синхронизацию каталога.
          </p>
        ) : null}
      </div>

      <div className="flex max-w-3xl flex-col gap-2">
        <Label htmlFor="template-formula">Формула шаблона</Label>
        <textarea
          id="template-formula"
          className="min-h-[96px] w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
          value={templateString}
          onChange={(e) => setTemplateString(e.target.value)}
          placeholder="{part_type} {brand} {make} {model}"
          spellCheck={false}
        />
        <div className="flex flex-wrap gap-2">
          {(tokensQuery.data ?? []).map((t) => (
            <button
              key={t.token}
              type="button"
              className="inline-flex items-center rounded-md border border-border bg-muted/40 px-2 py-0.5 font-mono text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
              title={t.description}
              onClick={() =>
                setTemplateString((prev) =>
                  prev.trim() ? `${prev.trim()} ${t.token}` : t.token,
                )
              }
            >
              {t.token}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap gap-2 pt-1">
          <Button
            type="button"
            size="sm"
            disabled={!selectedCategory || !templateString.trim() || saveMutation.isPending}
            onClick={() => saveMutation.mutate()}
          >
            {saveMutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Save className="h-4 w-4" />
            )}
            Сохранить шаблон
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={
              !selectedCategory ||
              !savedTemplateQuery.data ||
              deleteMutation.isPending
            }
            onClick={() => deleteMutation.mutate()}
          >
            <Trash2 className="h-4 w-4" />
            Сбросить привязку
          </Button>
        </div>
      </div>

      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-lg font-medium text-foreground">Live Preview</h2>
          {previewLoading ? (
            <Badge variant="secondary" className="gap-1">
              <Loader2 className="h-3 w-3 animate-spin" />
              Обновление…
            </Badge>
          ) : null}
          {previewQuery.data?.sample_source ? (
            <Badge variant="outline">
              источник: {previewQuery.data.sample_source}
            </Badge>
          ) : null}
        </div>

        {!selectedCategory ? (
          <p className="text-sm text-muted-foreground">
            Выберите категорию, чтобы увидеть превью на 3 товарах.
          </p>
        ) : previewQuery.isError ? (
          <p className="text-sm text-destructive">
            {previewQuery.error instanceof Error
              ? previewQuery.error.message
              : "Ошибка превью"}
          </p>
        ) : (
          <div className="rounded-md border border-border bg-card">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="min-w-[280px]">Имя в Odoo</TableHead>
                  <TableHead className="min-w-[280px]">Сгенерированное имя</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {previewQuery.isLoading && !previewQuery.data ? (
                  <TableRow>
                    <TableCell colSpan={2} className="h-20 text-center">
                      <span className="inline-flex items-center gap-2 text-muted-foreground">
                        <Loader2 className="h-4 w-4 animate-spin" />
                        Загрузка превью…
                      </span>
                    </TableCell>
                  </TableRow>
                ) : previewQuery.data?.items.length ? (
                  previewQuery.data.items.map((item, idx) => (
                    <TableRow key={item.odoo_id ?? idx}>
                      <TableCell className="align-top text-sm">
                        {item.odoo_name || "—"}
                      </TableCell>
                      <TableCell className="align-top text-sm font-medium">
                        {item.generated_name || (
                          <span className="text-muted-foreground">—</span>
                        )}
                        {item.warnings.length ? (
                          <p className="mt-1 text-xs text-amber-600">
                            {item.warnings.join("; ")}
                          </p>
                        ) : null}
                      </TableCell>
                    </TableRow>
                  ))
                ) : (
                  <TableRow>
                    <TableCell
                      colSpan={2}
                      className="h-20 text-center text-muted-foreground"
                    >
                      В категории нет товаров для превью
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
        )}
      </div>
    </div>
  );
}
