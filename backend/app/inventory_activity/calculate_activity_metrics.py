from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal


def total(events: list[dict], field: str) -> str | None:
    if any(e[field] is None for e in events):
        return None
    return format(sum((Decimal(e[field]) for e in events), Decimal(0)), "f")


def calculate_activity_metrics(materials: list[dict], events: list[dict], run: dict) -> tuple[list[dict], dict]:
    by_code = defaultdict(list)
    for event in events:
        if event["transaction_date"] <= run["observation_date"]:
            by_code[event["material_code"]].append(event)
    observations, summaries = [], {}
    obs_date = date.fromisoformat(run["observation_date"])
    year_start = f"{obs_date.year}-01-01"
    for material in materials:
        code = material["material_code"]
        history = sorted(by_code[code], key=lambda e: (e["transaction_date"], e["excel_row"]))
        last_date = history[-1]["transaction_date"] if history else None
        latest = [e for e in history if e["transaction_date"] == last_date]
        # Never use future metadata as if it were known at the observation date.
        if history:
            for key in ("material_name", "material_specification", "material_category", "unit"):
                material[key] = history[-1][key]
            material["metadata_source_record_id"] = history[-1]["source_record_id"]
        window = [e for e in history if run["frequency_window_start"] <= e["transaction_date"] <= run["frequency_window_end"]]
        annual = [e for e in history if year_start <= e["transaction_date"]]
        ins = [e for e in annual if e["transaction_type"] == "inbound"]
        outs = [e for e in annual if e["transaction_type"] == "outbound"]
        incompatible_units = len({e["unit"] for e in annual}) > 1
        values = {
            "DaysSinceLastMovement": ((obs_date - date.fromisoformat(last_date)).days if last_date else None, latest, "day"),
            "MovementFrequency": (len(window), window, "event"),
            "AnnualOutboundQuantity": (None if incompatible_units else total(outs, "quantity"), outs, material["unit"]),
            "AnnualInboundQuantity": (None if incompatible_units else total(ins, "quantity"), ins, material["unit"]),
            "AnnualOutboundValue": (total(outs, "amount"), outs, "CNY"),
            "AnnualInboundValue": (total(ins, "amount"), ins, "CNY"),
            "InboundFrequency": (sum(e["transaction_type"] == "inbound" for e in window), [e for e in window if e["transaction_type"] == "inbound"], "event"),
            "OutboundFrequency": (sum(e["transaction_type"] == "outbound" for e in window), [e for e in window if e["transaction_type"] == "outbound"], "event"),
        }
        for kind, direction in (("DaysSinceLastInbound", "inbound"), ("DaysSinceLastOutbound", "outbound")):
            directional = [e for e in history if e["transaction_type"] == direction]
            last = directional[-1]["transaction_date"] if directional else None
            values[kind] = ((obs_date - date.fromisoformat(last)).days if last else None,
                            [e for e in directional if e["transaction_date"] == last], "day")
        ids = []
        for kind, (value, evidence, unit) in values.items():
            metric_id = f"metric/{run['run_id']}/{code}/{kind}"
            ids.append(metric_id)
            start = year_start if kind.startswith("Annual") else run["frequency_window_start"] if "Frequency" in kind else run["data_window_start"]
            end = run["frequency_window_end"] if "Frequency" in kind else run["observation_date"]
            complete_window = start >= run["data_window_start"] and end <= run["data_window_end"]
            observations.append({
                "observation_id": metric_id, "material_code": code, "metric_type": kind,
                "numeric_value": value, "unit": unit, "observation_date": run["observation_date"],
                "window_start": start, "window_end": end,
                "data_window_start": run["data_window_start"], "data_window_end": run["data_window_end"],
                "status": "unavailable" if value is None else "partial_window" if not complete_window else "observed",
                "last_movement_date": evidence[-1]["transaction_date"] if kind.startswith("DaysSince") and evidence else None,
                "last_movement_event_ids": [e["movement_id"] for e in evidence] if kind.startswith("DaysSince") else [],
                "evidence_event_ids": [e["movement_id"] for e in evidence],
                "unavailable_reason": "unit_conflict" if incompatible_units and kind.endswith("Quantity") else "missing_amount" if value is None and kind.endswith("Value") else "no_observed_movement" if value is None else None,
                "quantity_by_unit": {u: total([e for e in evidence if e["unit"] == u], "quantity") for u in sorted({e["unit"] for e in evidence})} if kind.endswith("Quantity") else None,
            })
        summaries[code] = {
            "last_movement_date": last_date, "last_movement_event_ids": [e["movement_id"] for e in latest],
            "last_movement_event_id": latest[-1]["movement_id"] if latest else None,
            "last_movement_type": latest[-1]["transaction_type"] if latest else None,
            "last_movement_quantity": latest[-1]["quantity"] if latest else None,
            "source_record_id": latest[-1]["source_record_id"] if latest else None,
            "days_since_last_movement": values["DaysSinceLastMovement"][0],
            "movement_frequency": values["MovementFrequency"][0],
            "annual_outbound_quantity": values["AnnualOutboundQuantity"][0],
            "annual_outbound_value": values["AnnualOutboundValue"][0],
            "annual_outbound_quantity_by_unit": {unit: total([e for e in outs if e["unit"] == unit], "quantity") for unit in sorted({e["unit"] for e in outs})},
            "annual_inbound_quantity_by_unit": {unit: total([e for e in ins if e["unit"] == unit], "quantity") for unit in sorted({e["unit"] for e in ins})},
            "quantity_aggregation_status": "unit_conflict" if incompatible_units else "observed",
            "metric_observation_ids": ids,
        }
    return observations, summaries
