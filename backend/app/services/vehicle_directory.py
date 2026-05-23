"""Shared mock vehicle directory (until Base-Auto import)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.schemas.vehicle import VehicleGeneration, VehicleMake, VehicleModel

MAKES: list[VehicleMake] = [
    VehicleMake(id=1, name="BMW"),
    VehicleMake(id=2, name="Lada"),
    VehicleMake(id=3, name="Toyota"),
    VehicleMake(id=4, name="Volkswagen"),
    VehicleMake(id=5, name="Kia"),
]

MODELS: list[VehicleModel] = [
    VehicleModel(id=101, make_id=1, name="3 Series"),
    VehicleModel(id=102, make_id=1, name="5 Series"),
    VehicleModel(id=103, make_id=1, name="X5"),
    VehicleModel(id=201, make_id=2, name="Vesta"),
    VehicleModel(id=202, make_id=2, name="Granta"),
    VehicleModel(id=203, make_id=2, name="Largus"),
    VehicleModel(id=301, make_id=3, name="Camry"),
    VehicleModel(id=302, make_id=3, name="RAV4"),
    VehicleModel(id=401, make_id=4, name="Polo"),
    VehicleModel(id=402, make_id=4, name="Tiguan"),
    VehicleModel(id=501, make_id=5, name="Rio"),
    VehicleModel(id=502, make_id=5, name="Sportage"),
]

GENERATIONS: list[VehicleGeneration] = [
    VehicleGeneration(id=1001, model_id=101, name="E90 (2005–2011)"),
    VehicleGeneration(id=1002, model_id=101, name="F30 (2012–2018)"),
    VehicleGeneration(id=1003, model_id=101, name="G20 (2019–н.в.)"),
    VehicleGeneration(id=1101, model_id=102, name="E60 (2003–2010)"),
    VehicleGeneration(id=1102, model_id=102, name="F10 (2010–2017)"),
    VehicleGeneration(id=1201, model_id=103, name="E53 (2000–2006)"),
    VehicleGeneration(id=1202, model_id=103, name="F15 (2013–2018)"),
    VehicleGeneration(id=2001, model_id=201, name="I (2015–2021)"),
    VehicleGeneration(id=2002, model_id=201, name="II (2022–н.в.)"),
    VehicleGeneration(id=2101, model_id=202, name="I (2011–2018)"),
    VehicleGeneration(id=2102, model_id=202, name="II (2018–н.в.)"),
    VehicleGeneration(id=2201, model_id=203, name="I (2012–2020)"),
    VehicleGeneration(id=3001, model_id=301, name="XV50 (2011–2017)"),
    VehicleGeneration(id=3002, model_id=301, name="XV70 (2017–н.в.)"),
    VehicleGeneration(id=3101, model_id=302, name="XA40 (2013–2018)"),
    VehicleGeneration(id=3102, model_id=302, name="XA50 (2019–н.в.)"),
    VehicleGeneration(id=4001, model_id=401, name="Mk5 (2009–2017)"),
    VehicleGeneration(id=4002, model_id=401, name="Mk6 (2017–н.в.)"),
    VehicleGeneration(id=4101, model_id=402, name="5N (2007–2016)"),
    VehicleGeneration(id=4102, model_id=402, name="AD1 (2016–н.в.)"),
    VehicleGeneration(id=5001, model_id=501, name="III (2011–2017)"),
    VehicleGeneration(id=5002, model_id=501, name="IV (2017–н.в.)"),
    VehicleGeneration(id=5101, model_id=502, name="QL (2016–2021)"),
    VehicleGeneration(id=5102, model_id=502, name="NQ5 (2021–н.в.)"),
]

_MAKE_BY_ID = {m.id: m for m in MAKES}
_MODEL_BY_ID = {m.id: m for m in MODELS}
_GENERATION_BY_ID = {g.id: g for g in GENERATIONS}

_GENERATION_LABEL_RE = re.compile(
    r"^(.+?)\s*\((\d{4})\s*[–\-]\s*(\d{4}|н\.в\.)\)\s*$",
)


class VehicleDirectoryError(ValueError):
    """Invalid or inconsistent vehicle directory selection."""


@dataclass(frozen=True)
class ResolvedVehicleFitment:
    make_id: int
    model_id: int
    generation_id: int
    make: str
    model: str
    body: str | None
    year_from: int | None
    year_to: int | None


def parse_generation_label(name: str) -> tuple[str, int | None, int | None]:
    """Extract body code and year range from a generation display label."""
    text = (name or "").strip()
    match = _GENERATION_LABEL_RE.match(text)
    if not match:
        return text, None, None
    body = match.group(1).strip()
    year_from = int(match.group(2))
    end = match.group(3)
    year_to = 0 if end == "н.в." else int(end)
    return body, year_from, year_to


def resolve_vehicle_selection(
    *,
    make_id: int,
    model_id: int,
    generation_id: int,
) -> ResolvedVehicleFitment:
    """Map directory ids to naming-ready text fields."""
    make = _MAKE_BY_ID.get(make_id)
    if make is None:
        raise VehicleDirectoryError("Марка не найдена")

    model = _MODEL_BY_ID.get(model_id)
    if model is None:
        raise VehicleDirectoryError("Модель не найдена")
    if model.make_id != make_id:
        raise VehicleDirectoryError("Модель не принадлежит выбранной марке")

    generation = _GENERATION_BY_ID.get(generation_id)
    if generation is None:
        raise VehicleDirectoryError("Поколение не найдено")
    if generation.model_id != model_id:
        raise VehicleDirectoryError("Поколение не принадлежит выбранной модели")

    body, year_from, year_to = parse_generation_label(generation.name)
    return ResolvedVehicleFitment(
        make_id=make_id,
        model_id=model_id,
        generation_id=generation_id,
        make=make.name,
        model=model.name,
        body=body or None,
        year_from=year_from,
        year_to=year_to,
    )
