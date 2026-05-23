/** Vehicle applicability matrix DTOs — mirror backend/app/schemas/vehicle.py */

export type VehicleMake = {
  id: number;
  name: string;
};

export type VehicleModel = {
  id: number;
  make_id: number;
  name: string;
};

export type VehicleGeneration = {
  id: number;
  model_id: number;
  name: string;
};

export async function fetchVehicleMakes(): Promise<VehicleMake[]> {
  const res = await fetch("/api/vehicles/makes");
  if (!res.ok) {
    throw new Error(`Марки: HTTP ${res.status}`);
  }
  return res.json() as Promise<VehicleMake[]>;
}

export async function fetchVehicleModels(makeId: number): Promise<VehicleModel[]> {
  const qs = new URLSearchParams({ make_id: String(makeId) });
  const res = await fetch(`/api/vehicles/models?${qs}`);
  if (!res.ok) {
    throw new Error(`Модели: HTTP ${res.status}`);
  }
  return res.json() as Promise<VehicleModel[]>;
}

export async function fetchVehicleGenerations(
  modelId: number,
): Promise<VehicleGeneration[]> {
  const qs = new URLSearchParams({ model_id: String(modelId) });
  const res = await fetch(`/api/vehicles/generations?${qs}`);
  if (!res.ok) {
    throw new Error(`Поколения: HTTP ${res.status}`);
  }
  return res.json() as Promise<VehicleGeneration[]>;
}
