from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[3]
CONFIG_DIR = Path(os.environ.get("ACTIVITY_CONFIG_DIR", ROOT / "config"))
ONTOLOGY_PATH = Path(os.environ.get("ACTIVITY_ONTOLOGY_PATH", ROOT / "ontology/inventory-activity.ttl"))
SCHEMA_VERSION = "inventory-activity-v0.1"


class ActivityError(ValueError):
    pass


def json_default(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    raise TypeError(f"Unsupported JSON value: {type(value)}")


def dumps(value: Any, **kwargs: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=json_default, allow_nan=False, **kwargs)


def digest(value: Any) -> str:
    return hashlib.sha256(dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def read_config(path: Path) -> dict:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ActivityError(f"配置必须是映射: {path.name}")
    return json.loads(dumps(value))


def defaults() -> dict:
    return {**read_config(CONFIG_DIR / "inventory-activity.yaml"),
            "policy": read_config(CONFIG_DIR / "slow-moving-policy.yaml")}


def iso_date(value: Any, label: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise ActivityError(f"{label}必须为 ISO 日期 YYYY-MM-DD") from exc
