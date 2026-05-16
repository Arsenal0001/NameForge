"""Canonical part name model (Pydantic v2)."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class PartName(BaseModel):
    prefix: Optional[str] = None
    category: str = ""
    fitment: Optional[list[str]] = None
    specs: list[str] = Field(default_factory=list)
    colors: list[str] = Field(default_factory=list)
    brand: str = "NON"
    serial: Optional[int] = None

    def to_string(self) -> str:
        parts: list[str] = []
        if self.prefix:
            parts.append(f"{self.prefix}")
        parts.append(f"{{{{{self.category}}}}}")
        if self.fitment:
            for f in self.fitment:
                ft = (f or "").strip()
                if ft:
                    parts.append(f">{ft}<")
        for sp in self.specs:
            s = (sp or "").strip()
            if s:
                parts.append(f"[{s}]")
        for c in self.colors:
            col = (c or "").strip()
            if col:
                parts.append(f"(({col}))")
        parts.append(f"[[{self.brand}]]")
        if self.serial is not None:
            parts.append(f"#{self.serial}")
        return " ".join(parts)
