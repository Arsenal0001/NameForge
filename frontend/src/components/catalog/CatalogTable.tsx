import { useMemo, useState } from "react";
import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
  type PaginationState,
  type RowSelectionState,
} from "@tanstack/react-table";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CloudUpload, Loader2, Search } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
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
  pushProductsToOdoo,
  type ProductCatalogItem,
} from "@/lib/catalog-api";

const PAGE_SIZE_OPTIONS = [25, 50, 100] as const;

export function CatalogTable() {
  const queryClient = useQueryClient();
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  const [pagination, setPagination] = useState<PaginationState>({
    pageIndex: 0,
    pageSize: 50,
  });

  const selectedIds = useMemo(
    () =>
      Object.entries(rowSelection)
        .filter(([, selected]) => selected)
        .map(([id]) => Number(id)),
    [rowSelection],
  );

  const { data, isLoading, isFetching, isError, error } = useQuery({
    queryKey: ["products", pagination.pageIndex, pagination.pageSize],
    queryFn: () =>
      fetchProductCatalogPage(
        pagination.pageIndex * pagination.pageSize,
        pagination.pageSize,
      ),
    placeholderData: keepPreviousData,
  });

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
        accessorKey: "name",
        header: "Название",
        cell: ({ row }) => {
          const name =
            String(row.original.name || "").trim() || "—";
          const sk = row.original.search_keywords?.trim();
          return (
            <div className="flex max-w-[340px] min-w-0 items-center gap-1">
              <span className="min-w-0 flex-1 truncate" title={name}>
                {name}
              </span>
              {sk ? (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <button
                      type="button"
                      className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      aria-label="Поисковые ключевые слова"
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
          <span className="truncate">{String(getValue() || "—")}</span>
        ),
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
    mutationFn: pushProductsToOdoo,
    onSuccess: (res) => {
      void queryClient.invalidateQueries({ queryKey: ["products"] });
      setRowSelection({});
      const parts = [
        `Всего: ${res.total}`,
        `Успешно отправлено: ${res.pushed}`,
        `Пропущено (нет имени или ID): ${res.skipped}`,
      ];
      if (res.errors > 0) {
        parts.push(`Ошибок при отправке: ${res.errors}`);
      }
      toast.success("Выгрузка в Odoo завершена", {
        description: parts.join("\n"),
      });
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
      <div className="flex flex-1 flex-col gap-4 p-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">
          Каталог товаров
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Данные Odoo и статус блокировки имени. Пагинация на сервере.
        </p>
      </div>

      <div className="flex min-h-10 flex-wrap items-center gap-3">
        {selectedIds.length > 0 ? (
          <>
            <Button
              size="sm"
              disabled={generateMutation.isPending || pushMutation.isPending}
              onClick={() => generateMutation.mutate(selectedIds)}
            >
              {generateMutation.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : null}
              Сгенерировать названия ({selectedIds.length})
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={generateMutation.isPending || pushMutation.isPending}
              onClick={() => pushMutation.mutate(selectedIds)}
            >
              {pushMutation.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <CloudUpload className="mr-2 h-4 w-4" />
              )}
              Отправить в Odoo ({selectedIds.length})
            </Button>
          </>
        ) : (
          <span className="text-sm text-muted-foreground">
            Выберите позиции для пакетной генерации или выгрузки.
          </span>
        )}
        {isFetching ? (
          <span className="flex items-center gap-2 text-xs text-muted-foreground">
            <Loader2 className="h-3 w-3 animate-spin" />
            Обновление…
          </span>
        ) : null}
      </div>

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
            {isLoading ? (
              <TableRow>
                <TableCell
                  colSpan={columns.length}
                  className="h-24 text-center text-muted-foreground"
                >
                  Загрузка каталога…
                </TableCell>
              </TableRow>
            ) : isError ? (
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
    </TooltipProvider>
  );
}
