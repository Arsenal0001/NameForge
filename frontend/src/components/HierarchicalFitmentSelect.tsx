import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
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
import { Label } from "@/components/ui/label";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  fetchVehicleGenerations,
  fetchVehicleMakes,
  fetchVehicleModels,
  type VehicleGeneration,
  type VehicleMake,
  type VehicleModel,
} from "@/lib/vehicles-api";
import { cn } from "@/lib/utils";

export type FitmentSelection = {
  makeId: number | null;
  modelId: number | null;
  generationId: number | null;
};

type HierarchicalFitmentSelectProps = {
  value: FitmentSelection;
  onChange: (value: FitmentSelection) => void;
  disabled?: boolean;
  className?: string;
};

type VehicleComboboxProps<T extends { id: number; name: string }> = {
  label: string;
  placeholder: string;
  searchPlaceholder: string;
  emptyMessage: string;
  items: T[];
  valueId: number | null;
  onChange: (id: number | null) => void;
  disabled?: boolean;
  loading?: boolean;
};

function VehicleCombobox<T extends { id: number; name: string }>({
  label,
  placeholder,
  searchPlaceholder,
  emptyMessage,
  items,
  valueId,
  onChange,
  disabled = false,
  loading = false,
}: VehicleComboboxProps<T>) {
  const [open, setOpen] = useState(false);

  const sorted = useMemo(
    () => [...items].sort((a, b) => a.name.localeCompare(b.name, "ru")),
    [items],
  );

  const selected = sorted.find((item) => item.id === valueId) ?? null;

  return (
    <div className="grid gap-2">
      <Label>{label}</Label>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            type="button"
            variant="outline"
            role="combobox"
            aria-expanded={open}
            disabled={disabled || loading}
            className="w-full justify-between font-normal"
          >
            {loading
              ? "Загрузка…"
              : selected
                ? selected.name
                : placeholder}
            <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-[min(24rem,90vw)] p-0" align="start">
          <Command
            filter={(itemValue, search) => {
              if (!search.trim()) return 1;
              const q = search.trim().toLowerCase();
              return itemValue.toLowerCase().includes(q) ? 1 : 0;
            }}
          >
            <CommandInput placeholder={searchPlaceholder} />
            <CommandList>
              <CommandEmpty>{emptyMessage}</CommandEmpty>
              <CommandGroup>
                {sorted.map((item) => (
                  <CommandItem
                    key={item.id}
                    value={`${item.name} ${item.id}`}
                    onSelect={() => {
                      onChange(item.id);
                      setOpen(false);
                    }}
                  >
                    <Check
                      className={cn(
                        "mr-2 h-4 w-4",
                        valueId === item.id ? "opacity-100" : "opacity-0",
                      )}
                    />
                    <span className="truncate">{item.name}</span>
                  </CommandItem>
                ))}
              </CommandGroup>
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
    </div>
  );
}

export function HierarchicalFitmentSelect({
  value,
  onChange,
  disabled = false,
  className,
}: HierarchicalFitmentSelectProps) {
  const makesQuery = useQuery({
    queryKey: ["vehicles", "makes"],
    queryFn: fetchVehicleMakes,
  });

  const modelsQuery = useQuery({
    queryKey: ["vehicles", "models", value.makeId],
    queryFn: () => fetchVehicleModels(value.makeId!),
    enabled: value.makeId != null,
  });

  const generationsQuery = useQuery({
    queryKey: ["vehicles", "generations", value.modelId],
    queryFn: () => fetchVehicleGenerations(value.modelId!),
    enabled: value.modelId != null,
  });

  const handleMakeChange = (makeId: number | null) => {
    onChange({
      makeId,
      modelId: null,
      generationId: null,
    });
  };

  const handleModelChange = (modelId: number | null) => {
    onChange({
      makeId: value.makeId,
      modelId,
      generationId: null,
    });
  };

  const handleGenerationChange = (generationId: string) => {
    onChange({
      ...value,
      generationId: Number(generationId),
    });
  };

  const generations = generationsQuery.data ?? [];
  const generationValue =
    value.generationId != null ? String(value.generationId) : undefined;

  return (
    <div className={cn("grid gap-4 sm:grid-cols-3", className)}>
      <VehicleCombobox<VehicleMake>
        label="Марка"
        placeholder="Выберите марку…"
        searchPlaceholder="Поиск марки…"
        emptyMessage="Марка не найдена"
        items={makesQuery.data ?? []}
        valueId={value.makeId}
        onChange={handleMakeChange}
        disabled={disabled}
        loading={makesQuery.isLoading}
      />

      <VehicleCombobox<VehicleModel>
        label="Модель"
        placeholder="Сначала выберите марку"
        searchPlaceholder="Поиск модели…"
        emptyMessage="Модель не найдена"
        items={modelsQuery.data ?? []}
        valueId={value.modelId}
        onChange={handleModelChange}
        disabled={disabled || value.makeId == null}
        loading={value.makeId != null && modelsQuery.isLoading}
      />

      <div className="grid gap-2">
        <Label htmlFor="fitment-generation">Поколение</Label>
        <Select
          value={generationValue}
          onValueChange={handleGenerationChange}
          disabled={disabled || value.modelId == null || generationsQuery.isLoading}
        >
          <SelectTrigger id="fitment-generation">
            <SelectValue
              placeholder={
                value.modelId == null
                  ? "Сначала выберите модель"
                  : generationsQuery.isLoading
                    ? "Загрузка…"
                    : "Выберите поколение…"
              }
            />
          </SelectTrigger>
          <SelectContent>
            {generations.map((gen: VehicleGeneration) => (
              <SelectItem key={gen.id} value={String(gen.id)}>
                {gen.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </div>
  );
}
