import { useMemo, useState } from "react";
import { Check, ChevronsUpDown } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { categoryLabel } from "@/lib/templates-api";
import type { CategoryRow } from "@/lib/categories-api";
import { cn } from "@/lib/utils";

type SmartCategoryComboboxProps = {
  categories: CategoryRow[];
  value: CategoryRow | null;
  onChange: (row: CategoryRow | null) => void;
  disabled?: boolean;
  loading?: boolean;
};

export function SmartCategoryCombobox({
  categories,
  value,
  onChange,
  disabled = false,
  loading = false,
}: SmartCategoryComboboxProps) {
  const [open, setOpen] = useState(false);

  const sorted = useMemo(
    () =>
      [...categories].sort((a, b) =>
        categoryLabel(a).localeCompare(categoryLabel(b), "ru"),
      ),
    [categories],
  );

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          role="combobox"
          aria-expanded={open}
          disabled={disabled || loading}
          className="w-full max-w-xl justify-between font-normal"
        >
          {loading
            ? "Загрузка категорий…"
            : value
              ? categoryLabel(value)
              : "Выберите категорию Odoo…"}
          <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-[min(32rem,90vw)] p-0" align="start">
        <Command filter={(itemValue, search) => {
          if (!search.trim()) return 1;
          const q = search.trim().toLowerCase();
          return itemValue.toLowerCase().includes(q) ? 1 : 0;
        }}>
          <CommandInput placeholder="Поиск по названию или пути…" />
          <CommandList>
            <CommandEmpty>Категория не найдена</CommandEmpty>
            <CommandGroup>
              {sorted.map((row) => {
                const label = categoryLabel(row);
                return (
                  <CommandItem
                    key={row.odoo_id}
                    value={`${label} ${row.odoo_id}`}
                    onSelect={() => {
                      onChange(row);
                      setOpen(false);
                    }}
                  >
                    <Check
                      className={cn(
                        "mr-2 h-4 w-4",
                        value?.odoo_id === row.odoo_id ? "opacity-100" : "opacity-0",
                      )}
                    />
                    <div className="flex min-w-0 flex-col">
                      <span className="truncate">{label}</span>
                      <span className="text-xs text-muted-foreground">
                        id {row.odoo_id}
                      </span>
                    </div>
                  </CommandItem>
                );
              })}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
