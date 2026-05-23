import { useCallback, useEffect, useMemo, useState } from "react";
import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
  type PaginationState,
  type RowSelectionState,
} from "@tanstack/react-table";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Loader2, Search, CarFront } from "lucide-react";
import { toast } from "sonner";

import { CatalogBatchActionsBar } from "@/components/catalog/CatalogBatchActionsBar";
import { CatalogTableSkeleton } from "@/components/catalog/CatalogTableSkeleton";
import {
  EMPTY_FITMENT,
  FitmentEditorSheet,
} from "@/components/catalog/FitmentEditorSheet";
import { NamingStatusBadge } from "@/components/catalog/NamingStatusBadge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  batchGenerateNames,
  fetchProductCatalogPage,
  syncProductsToOdoo,
  type CatalogQueryFilters,
  type NamingStatus,
  type ProductCatalogItem,
  type ProductCatalogPage,
} from "@/lib/catalog-api";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { cn } from "@/lib/utils";
import type { FitmentSelection } from "@/components/HierarchicalFitmentSelect";

const PAGE_SIZE_OPTIONS = [25, 50, 100] as const;
const FILTER_ALL = "all" as const;
const SEARCH_DEBOUNCE_MS = 400;

type TriStateFilter = typeof FILTER_ALL | "true" | "false";

type CatalogTableMeta = {
  openFitmentEditor: (item: ProductCatalogItem) => void;
};

function LongTextCell({ value, maxWidthClass = "max-w-[220px]" }: { value: string; maxWidthClass?: string }) {
  const text = value.trim() || "—";
  if (text === "—") {
    return <span className="text-muted-foreground">—</span>;
  }
  return (
    <span
      className={`block min-w-0 truncate ${maxWidthClass}`}
      title={text}
    >
      {text}
    </span>
  );
}

export function CatalogTable() {
  const queryClient = useQueryClient();
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  const [fitmentSheetOpen, setFitmentSheetOpen] = useState(false);
  const [fitmentProduct, setFitmentProduct] = useState<ProductCatalogItem | null>(
    null,
  );
  const [fitment, setFitment] = useState<FitmentSelection>(EMPTY_FITMENT);
  const [pagination, setPagination] = useState<PaginationState>({
    pageIndex: 0,
    pageSize: 50,
  });
  const [searchInput, setSearchInput] = useState("");
  const debouncedSearch = useDebouncedValue(searchInput, SEARCH_DEBOUNCE_MS);
  const [namingStatusFilter, setNamingStatusFilter] = useState<
    NamingStatus | typeof FILTER_ALL
  >(FILTER_ALL);
  const [lockedFilter, setLockedFilter] = useState<TriStateFilter>(FILTER_ALL);
  const [errorFilter, setErrorFilter] = useState<TriStateFilter>(FILTER_ALL);

  const catalogFilters = useMemo((): CatalogQueryFilters => {
    const filters: CatalogQueryFilters = {};
    const search = debouncedSearch.trim();
    if (search) {
      filters.search = search;
    }
    if (namingStatusFilter !== FILTER_ALL) {
      filters.naming_status = namingStatusFilter;
    }
    if (lockedFilter === "true") {
      filters.is_locked = true;
    } else if (lockedFilter === "false") {
      filters.is_locked = false;
    }
    if (errorFilter === "true") {
      filters.has_error = true;
    } else if (errorFilter === "false") {
      filters.has_error = false;
    }
    return filters;
  }, [debouncedSearch, namingStatusFilter, lockedFilter, errorFilter]);

  useEffect(() => {
    setPagination((current) =>
      current.pageIndex === 0 ? current : { ...current, pageIndex: 0 },
    );
  }, [debouncedSearch, namingStatusFilter, lockedFilter, errorFilter]);

  const catalogQueryKey = useMemo(
    () =>
      [
        "products",
        pagination.pageIndex,
        pagination.pageSize,
        catalogFilters,
      ] as const,
    [pagination.pageIndex, pagination.pageSize, catalogFilters],
  );

  const selectedIds = useMemo(
    () =>
      Object.entries(rowSelection)
        .filter(([, selected]) => selected)
        .map(([id]) => Number(id)),
    [rowSelection],
  );

  const { data, isLoading, isFetching, isError, error } = useQuery({
    queryKey: catalogQueryKey,
    queryFn: () =>
      fetchProductCatalogPage(
        pagination.pageIndex * pagination.pageSize,
        pagination.pageSize,
        catalogFilters,
      ),
    placeholderData: keepPreviousData,
  });

  const handleFitmentSheetOpenChange = useCallback((open: boolean) => {
    setFitmentSheetOpen(open);
    if (!open) {
      setFitmentProduct(null);
      setFitment(EMPTY_FITMENT);
    }
  }, []);

  const openFitmentEditor = useCallback((item: ProductCatalogItem) => {
    setFitmentProduct(item);
    setFitment(EMPTY_FITMENT);
    setFitmentSheetOpen(true);
  }, []);

  const columns = useMemo<ColumnDef<ProductCatalogItem>[]>(
    () => [
      {
        id: "select",
        header: ({ table }) => (
          <Checkbox
            checked={
              table.getIsAllPageRowsSelected()
                ? true
                : table.getIsSomePageRowsSelected()
                  ? "indeterminate"
                  : false
            }
            onCheckedChange={(value) =>
              table.toggleAllPageRowsSelected(!!value)
            }
            aria-label="Выбрать все на странице"
          />
        ),
        cell: ({ row }) => (
          <Checkbox
            checked={row.getIsSelected()}
            onCheckedChange={(value) => row.toggleSelected(!!value)}
            aria-label={`Выбрать товар ${row.original.id}`}
          />
        ),
        enableSorting: false,
        enableHiding: false,
        size: 40,
      },
      {
        accessorKey: "article",
        header: "Артикул",
        cell: ({ getValue }) => (
          <span className="font-mono text-xs">{String(getValue() || "—")}</span>
        ),
      },
      {
        accessorKey: "odoo_name",
        header: "Имя в Odoo",
        cell: ({ row }) => {
          const name =
            String(row.original.odoo_name || row.original.name || "").trim() || "—";
          return (
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="block min-w-0 max-w-[300px] truncate text-muted-foreground">
                  {name}
                </span>
              </TooltipTrigger>
              <TooltipContent
                side="top"
                align="start"
                className="max-w-lg whitespace-pre-wrap break-words"
              >
                {name}
              </TooltipContent>
            </Tooltip>
          );
        },
      },
      {
        id: "preview_name",
        header: "Сгенерированное имя (Превью)",
        cell: ({ row }) => {
          const preview = String(row.original.preview_name || "").trim();
          const sk = row.original.search_keywords?.trim();
          return (
            <div className="flex min-w-0 max-w-[360px] flex-col gap-1.5">
              <div className="flex items-center gap-1.5">
                <NamingStatusBadge status={row.original.naming_status} />
                {row.original.last_sync_error ? (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <button
                        type="button"
                        className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-destructive transition-colors hover:bg-destructive/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        aria-label="Ошибка синхронизации с Odoo"
                      >
                        <AlertTriangle className="h-4 w-4" aria-hidden />
                      </button>
                    </TooltipTrigger>
                    <TooltipContent
                      side="top"
                      align="start"
                      className="max-w-lg whitespace-pre-wrap break-words"
                    >
                      {row.original.last_sync_error}
                    </TooltipContent>
                  </Tooltip>
                ) : null}
              </div>
              {preview ? (
                <div className="flex min-w-0 items-center gap-1">
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <span
                        className={cn(
                          "min-w-0 flex-1 truncate font-medium",
                          row.original.naming_status === "synced"
                            ? "text-emerald-800 dark:text-emerald-300"
                            : "text-foreground",
                        )}
                      >
                        {preview}
                      </span>
                    </TooltipTrigger>
                    <TooltipContent
                      side="top"
                      align="start"
                      className="max-w-xl whitespace-pre-wrap break-words"
                    >
                      {preview}
                    </TooltipContent>
                  </Tooltip>
                  {sk ? (
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <button
                          type="button"
                          className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                          aria-label="Поисковые ключевые слова превью"
                        >
                          <Search className="h-4 w-4" aria-hidden />
                        </button>
                      </TooltipTrigger>
                      <TooltipContent
                        side="top"
                        align="start"
                        className="max-w-lg whitespace-pre-wrap break-words"
                      >
                        {sk}
                      </TooltipContent>
                    </Tooltip>
                  ) : null}
                </div>
              ) : (
                <span className="text-sm text-muted-foreground">—</span>
              )}
            </div>
          );
        },
      },
      {
        id: "category",
        header: "Категория",
        cell: ({ row }) => (
          <div className="flex min-w-0 max-w-[280px] items-center gap-2">
            <span className="min-w-0 flex-1 truncate" title={row.original.category}>
              {row.original.category || "—"}
            </span>
            <Badge
              variant="outline"
              className="shrink-0 px-1.5 py-0 text-[10px] font-normal text-muted-foreground"
              title={
                row.original.category_template_bound
                  ? "К категории привязан шаблон генерации"
                  : "Шаблон категории не привязан"
              }
            >
              {row.original.category_template_bound ? "шаблон" : "—"}
            </Badge>
          </div>
        ),
      },
      {
        accessorKey: "brand",
        header: "Бренд",
        cell: ({ getValue }) => (
          <LongTextCell value={String(getValue() || "")} maxWidthClass="max-w-[140px]" />
        ),
      },
      {
        accessorKey: "primary_make",
        header: "Марка",
        cell: ({ getValue }) => (
          <LongTextCell value={String(getValue() || "")} />
        ),
      },
      {
        accessorKey: "primary_model",
        header: "Модель",
        cell: ({ getValue }) => (
          <LongTextCell value={String(getValue() || "")} />
        ),
      },
      {
        accessorKey: "fitment_summary",
        header: "Спецификации",
        cell: ({ row }) => {
          const summary = String(row.original.fitment_summary || "").trim();
          if (!summary) {
            return <span className="text-muted-foreground">—</span>;
          }
          return (
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="block min-w-0 max-w-[260px] cursor-help truncate">
                  {summary}
                </span>
              </TooltipTrigger>
              <TooltipContent
                side="top"
                align="start"
                className="max-w-xl whitespace-pre-wrap break-words"
              >
                {summary}
              </TooltipContent>
            </Tooltip>
          );
        },
      },
      {
        accessorKey: "name_locked",
        header: "Имя заблокировано",
        cell: ({ getValue }) => {
          const locked = Boolean(getValue());
          return (
            <Badge variant={locked ? "destructive" : "secondary"}>
              {locked ? "Да" : "Нет"}
            </Badge>
          );
        },
      },
      {
        id: "actions",
        header: () => <span className="sr-only">Действия</span>,
        cell: ({ row, table }) => {
          const meta = table.options.meta as CatalogTableMeta | undefined;
          return (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8 shrink-0"
                  aria-label={`Применимость: ${row.original.article || row.original.id}`}
                  onClick={() => meta?.openFitmentEditor(row.original)}
                >
                  <CarFront className="h-4 w-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent side="left">Применимость</TooltipContent>
            </Tooltip>
          );
        },
        enableSorting: false,
        enableHiding: false,
        size: 48,
      },
    ],
    [],
  );

  const pageCount =
    data !== undefined
      ? Math.ceil(data.total_count / pagination.pageSize)
      : 0;

  /* eslint-disable-next-line react-hooks/incompatible-library -- TanStack Table instance is inherently unstable */
  const table = useReactTable({
    data: data?.items ?? [],
    columns,
    state: {
      rowSelection,
      pagination,
    },
    enableRowSelection: true,
    onRowSelectionChange: setRowSelection,
    onPaginationChange: setPagination,
    getCoreRowModel: getCoreRowModel(),
    manualPagination: true,
    pageCount,
    getRowId: (row) => String(row.id),
    meta: {
      openFitmentEditor,
    },
  });

  const generateMutation = useMutation({
    mutationFn: batchGenerateNames,
    onSuccess: (res) => {
      void queryClient.invalidateQueries({ queryKey: ["products"] });
      setRowSelection({});
      const parts = [
        `Успешно обработано: ${res.ok_count}`,
        `Записано в БД: ${res.persisted_count}`,
        `Пропущено (блокировка имени): ${res.skipped_locked_count}`,
        `Пропущено (идемпотентность / без изменений): ${res.skipped_idempotent_count}`,
      ];
      if (res.errors.length > 0) {
        parts.push(`Ошибок по позициям: ${res.errors.length}`);
      }
      toast.success("Генерация названий завершена", {
        description: parts.join("\n"),
      });
      const skippedTotal =
        res.skipped_locked_count + res.skipped_idempotent_count;
      if (res.errors.length > 0) {
        toast.warning("Генерация с ошибками по части позиций", {
          description: `Сгенерировано (успешно обработано): ${res.ok_count}. Ошибок: ${res.errors.length}. Пропущено (блокировка + идемпотентность): ${skippedTotal}.`,
        });
      }
    },
    onError: (e: unknown) => {
      toast.error(
        e instanceof Error ? e.message : "Не удалось выполнить генерацию",
      );
    },
  });

  const pushMutation = useMutation({
    mutationFn: syncProductsToOdoo,
    onSuccess: (res) => {
      const syncedSet = new Set(res.synced_product_ids);
      queryClient.setQueryData<ProductCatalogPage>(catalogQueryKey, (old) => {
        if (!old) {
          return old;
        }
        return {
          ...old,
          items: old.items.map((item) =>
            syncedSet.has(item.id)
              ? {
                  ...item,
                  naming_status: "synced" as const,
                  odoo_name: item.preview_name || item.odoo_name,
                  last_sync_error: null,
                }
              : item,
          ),
        };
      });
      setRowSelection({});
      const parts = [
        res.dry_run ? "DRY_RUN: запись в Odoo не выполнялась" : "Синхронизация завершена",
        `Отправлено: ${res.pushed}`,
        `Пропущено (блокировка): ${res.skipped_locked}`,
        `Пропущено (идемпотентность): ${res.skipped_idempotent}`,
        `Пропущено (нет данных): ${res.skipped_invalid}`,
      ];
      if (res.errors > 0) {
        parts.push(`Ошибок: ${res.errors}`);
      }
      toast.success(
        res.dry_run ? "DRY RUN — симуляция отправки в Odoo" : "Выгрузка в Odoo завершена",
        { description: parts.join("\n") },
      );
      if (res.errors > 0) {
        toast.warning("Часть позиций не синхронизирована", {
          description: `Ошибок: ${res.errors}`,
        });
      }
      void queryClient.invalidateQueries({ queryKey: ["products"] });
    },
    onError: (e: unknown) => {
      toast.error(
        e instanceof Error ? e.message : "Не удалось выполнить выгрузку в Odoo",
      );
    },
  });

  const rangeStart =
    data && data.total_count > 0 ? data.offset + 1 : 0;
  const rangeEnd = data ? data.offset + data.items.length : 0;

  return (
    <TooltipProvider>
      <div className="flex min-h-0 flex-1 flex-col gap-4 p-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">
          Каталог товаров
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Spreadsheet-сравнение: имя в Odoo и превью Naming Engine в одной таблице.
        </p>
      </div>

      <div className="rounded-lg border border-border bg-card p-4">
        <div className="flex flex-col gap-4 lg:flex-row lg:flex-wrap lg:items-end">
          <div className="flex min-w-[220px] flex-1 flex-col gap-2">
            <Label htmlFor="catalog-search">Поиск</Label>
            <div className="relative">
              <Search className="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                id="catalog-search"
                value={searchInput}
                onChange={(event) => setSearchInput(event.target.value)}
                placeholder="Артикул, код, имя в Odoo или превью…"
                className="pl-9"
              />
            </div>
          </div>
          <div className="flex min-w-[180px] flex-col gap-2">
            <Label htmlFor="naming-status-filter">Статус имени</Label>
            <Select
              value={namingStatusFilter}
              onValueChange={(value) =>
                setNamingStatusFilter(value as NamingStatus | typeof FILTER_ALL)
              }
            >
              <SelectTrigger id="naming-status-filter">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={FILTER_ALL}>Все статусы</SelectItem>
                <SelectItem value="synced">Синхронизировано</SelectItem>
                <SelectItem value="pending_sync">Ожидает отправки</SelectItem>
                <SelectItem value="no_template">Нет шаблона</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="flex min-w-[160px] flex-col gap-2">
            <Label htmlFor="locked-filter">Блокировка имени</Label>
            <Select
              value={lockedFilter}
              onValueChange={(value) => setLockedFilter(value as TriStateFilter)}
            >
              <SelectTrigger id="locked-filter">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={FILTER_ALL}>Все</SelectItem>
                <SelectItem value="true">Заблокировано</SelectItem>
                <SelectItem value="false">Не заблокировано</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="flex min-w-[160px] flex-col gap-2">
            <Label htmlFor="error-filter">Ошибки sync</Label>
            <Select
              value={errorFilter}
              onValueChange={(value) => setErrorFilter(value as TriStateFilter)}
            >
              <SelectTrigger id="error-filter">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={FILTER_ALL}>Все</SelectItem>
                <SelectItem value="true">Только с ошибкой</SelectItem>
                <SelectItem value="false">Без ошибок</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
      </div>

      <CatalogBatchActionsBar
        selectedCount={selectedIds.length}
        isSyncPending={pushMutation.isPending}
        isGeneratePending={generateMutation.isPending}
        onSync={() => pushMutation.mutate(selectedIds)}
        onGenerate={() => generateMutation.mutate(selectedIds)}
      />

      <div className="relative">
        {isLoading ? (
          <CatalogTableSkeleton rows={pagination.pageSize > 10 ? 10 : pagination.pageSize} />
        ) : (
          <div className="rounded-md border border-border bg-card">
            <Table>
              <TableHeader>
                {table.getHeaderGroups().map((headerGroup) => (
                  <TableRow key={headerGroup.id}>
                    {headerGroup.headers.map((header) => (
                      <TableHead key={header.id}>
                        {header.isPlaceholder
                          ? null
                          : flexRender(
                              header.column.columnDef.header,
                              header.getContext(),
                            )}
                      </TableHead>
                    ))}
                  </TableRow>
                ))}
              </TableHeader>
              <TableBody>
                {isError ? (
                  <TableRow>
                    <TableCell
                      colSpan={columns.length}
                      className="h-24 text-center text-destructive"
                    >
                      {error instanceof Error ? error.message : "Ошибка загрузки"}
                    </TableCell>
                  </TableRow>
                ) : table.getRowModel().rows.length ? (
                  table.getRowModel().rows.map((row) => (
                    <TableRow
                      key={row.id}
                      data-state={row.getIsSelected() && "selected"}
                      className={cn(
                        row.original.name_locked &&
                          "opacity-60 bg-muted/30 hover:bg-muted/40",
                      )}
                    >
                      {row.getVisibleCells().map((cell) => (
                        <TableCell key={cell.id}>
                          {flexRender(
                            cell.column.columnDef.cell,
                            cell.getContext(),
                          )}
                        </TableCell>
                      ))}
                    </TableRow>
                  ))
                ) : (
                  <TableRow>
                    <TableCell
                      colSpan={columns.length}
                      className="h-24 text-center text-muted-foreground"
                    >
                      Нет строк для отображения.
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
        )}
        {isFetching && !isLoading ? (
          <div
            className="pointer-events-none absolute inset-x-0 top-0 h-0.5 overflow-hidden rounded-t-md bg-muted"
            aria-hidden
          >
            <div className="h-full w-1/3 animate-pulse bg-primary/40" />
          </div>
        ) : null}
      </div>

      {isFetching && !isLoading ? (
        <p className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="h-3 w-3 animate-spin" />
          Обновление данных…
        </p>
      ) : null}

      <div className="flex flex-wrap items-center justify-between gap-4">
        <p className="text-sm text-muted-foreground">
          {data && data.total_count > 0
            ? `Показано ${rangeStart}–${rangeEnd} из ${data.total_count}`
            : data
              ? "Нет товаров в базе"
              : null}
        </p>
        <div className="flex flex-wrap items-center gap-4">
          <div className="flex items-center gap-2">
            <Label htmlFor="page-size" className="text-sm whitespace-nowrap">
              На странице
            </Label>
            <Select
              value={String(pagination.pageSize)}
              onValueChange={(v) => {
                const next = Number(v);
                setPagination((p) => ({
                  ...p,
                  pageSize: next,
                  pageIndex: 0,
                }));
              }}
            >
              <SelectTrigger id="page-size" className="w-[88px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {PAGE_SIZE_OPTIONS.map((n) => (
                  <SelectItem key={n} value={String(n)}>
                    {n}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => table.previousPage()}
              disabled={!table.getCanPreviousPage()}
            >
              Назад
            </Button>
            <span className="text-sm text-muted-foreground">
              Стр. {pagination.pageIndex + 1}
              {pageCount > 0 ? ` / ${pageCount}` : ""}
            </span>
            <Button
              variant="outline"
              size="sm"
              onClick={() => table.nextPage()}
              disabled={!table.getCanNextPage()}
            >
              Вперёд
            </Button>
          </div>
        </div>
      </div>
      </div>

      <FitmentEditorSheet
        open={fitmentSheetOpen}
        product={fitmentProduct}
        fitment={fitment}
        onFitmentChange={setFitment}
        onOpenChange={handleFitmentSheetOpenChange}
        catalogQueryKey={catalogQueryKey}
      />
    </TooltipProvider>
  );
}
