from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Transaction:
    material_code: str
    material_name: str
    material_spec: str
    trans_date: date
    trans_type: str
    quantity: float
    amount: float
    material_category: str | None = None
    dept_name: str | None = None
    operator: str | None = None
    supplier: str | None = None


class DataQualityError(ValueError):
    def __init__(self, message: str, details: list[str] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or []
