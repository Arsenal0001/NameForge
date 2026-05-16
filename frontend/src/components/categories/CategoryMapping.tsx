import { useDeferredValue, useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
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
  fetchCategoriesPage,
  fetchNamingMatrices,
  putCategoryTemplate,
  type CategoryRow,
} from "@/lib/categories-api";

const NONE_VALUE = "__none__";
const PAGE_SIZE = 50;

export function CategoryMapping() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const deferredSearch = useDeferredValue(search);
  const [pageIndex, setPageIndex] = useState(0);
  const [busyOdooId, setBusyOdooId] = useState<number | null>(null);

  const matricesQuery = useQuery({
    queryKey: ["naming-matrices"],
    queryFn: fetchNamingMatrices,
    staleTime: Infinity,
  });

  const categoriesQuery = useQuery({
    queryKey: ["categories", deferredSearch, pageIndex, PAGE_SIZE],
    queryFn: () =>
      fetchCategoriesPage(deferredSearch, pageIndex * PAGE_SIZE, PAGE_SIZE),
    placeholderData: keepPreviousData,
  });

  const saveMutation = useMutation({
    mutationFn: ({
      odooId,
      key,
    }: {
      odooId: number;
      key: string | null;
    }) => putCategoryTemplate(odooId, key),
    onMutate: async ({ odooId }) => {
      setBusyOdooId(odooId);
    },
    onSettled: () => {
      setBusyOdooId(null);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["categories"] });
      void queryClient.invalidateQueries({ queryKey: ["products"] });
    },
    onError: (e: unknown) => {
      toast.error(
        e instanceof Error ? e.message : "Не удалось сохранить привязку",
      );
    },
  });

  const data = categoriesQuery.data;
  const pageCount =
    data !== undefined ? Math.ceil(data.total_count / PAGE_SIZE) : 0;

  const displayPath = (row: CategoryRow) =>
    (row.complete_name || "").trim() || row.name || "—";

  return (
    <div className="flex flex-1 flex-col gap-4 p-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">
          Настройка категорий
        </h1>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
          Кэш Odoo product.category: выберите матрицу генерации имени для группы
          товаров (см. NAMING_TEMPLATES.md). Связь сохраняется локально и
          участвует в расчёте имён при генерации.
        </p>
      </div>

      <div className="flex max-w-md flex-col gap-2">
        <Label htmlFor="cat-search">Поиск по имени или полному пути</Label>
        <Input
          id="cat-search"
          placeholder="Например: Коврики / Автохимия…"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setPageIndex(0);
          }}
        />
      </div>

      <div className="rounded-md border border-border bg-card">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="min-w-[240px]">Категория (Odoo)</TableHead>
              <TableHead className="w-[320px]">Матрица наименования</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {categoriesQuery.isLoading ? (
              <TableRow>
                <TableCell colSpan={2} className="h-24 text-center">
                  <span className="inline-flex items-center gap-2 text-muted-foreground">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Загрузка…
                  </span>
                </TableCell>
              </TableRow>
            ) : categoriesQuery.isError ? (
              <TableRow>
                <TableCell colSpan={2} className="h-24 text-center text-destructive">
                  Не удалось загрузить категории
                </TableCell>
              </TableRow>
            ) : data && data.items.length ? (
              data.items.map((row) => (
                <TableRow key={row.odoo_id}>
                  <TableCell>
                    <div className="flex flex-col gap-0.5">
                      <span className="font-medium text-foreground">
                        {displayPath(row)}
                      </span>
                      <span className="text-xs text-muted-foreground">
                        id {row.odoo_id}
                        {row.parent_id != null ? ` · parent ${row.parent_id}` : ""}
                      </span>
                    </div>
                  </TableCell>
                  <TableCell>
                    <Select
                      disabled={
                        matricesQuery.isLoading ||
                        !matricesQuery.data?.length ||
                        busyOdooId === row.odoo_id
                      }
                      value={row.naming_template_key ?? NONE_VALUE}
                      onValueChange={(v) => {
                        const next = v === NONE_VALUE ? null : v;
                        if (next === row.naming_template_key) {
                          return;
                        }
                        saveMutation.mutate({ odooId: row.odoo_id, key: next });
                      }}
                    >
                      <SelectTrigger className="w-full min-w-[260px]">
                        <SelectValue placeholder="Выберите матрицу" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value={NONE_VALUE}>Не выбрано</SelectItem>
                        {(matricesQuery.data ?? []).map((opt) => (
                          <SelectItem key={opt.matrix_id} value={opt.matrix_id}>
                            {opt.title}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </TableCell>
                </TableRow>
              ))
            ) : (
              <TableRow>
                <TableCell
                  colSpan={2}
                  className="h-24 text-center text-muted-foreground"
                >
                  Нет категорий в кэше. Выполните синхронизацию каталога Odoo.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-4">
        <p className="text-sm text-muted-foreground">
          {data && data.total_count > 0
            ? `Страница ${pageIndex + 1}${pageCount > 0 ? ` / ${pageCount}` : ""} · всего ${data.total_count}`
            : data
              ? "Нет данных"
              : null}
        </p>
        <div className="flex gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={pageIndex <= 0 || categoriesQuery.isFetching}
            onClick={() => setPageIndex((p) => Math.max(0, p - 1))}
          >
            Назад
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={
              pageCount === 0 ||
              pageIndex >= pageCount - 1 ||
              categoriesQuery.isFetching
            }
            onClick={() =>
              setPageIndex((p) => (pageCount ? Math.min(pageCount - 1, p + 1) : p))
            }
          >
            Вперёд
          </Button>
        </div>
      </div>
    </div>
  );
}
