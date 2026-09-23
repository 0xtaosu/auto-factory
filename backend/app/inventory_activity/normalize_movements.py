from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from openpyxl.utils.datetime import from_excel

from .common import digest

INBOUND = {"入库", "in", "inbound", "1", "收", "采购入库", "生产入库", "外协入库"}
OUTBOUND = {"出库", "out", "outbound", "-1", "发", "销售出库", "生产领料", "委外出库"}
TEXT_FIELDS = {"material_code": "物料编码", "material_name": "物料名称",
               "material_specification": "物料规格", "material_category": "物料类别",
               "unit": "单位", "department": "出入库部门", "supplier": "供应商名称",
               "operator": "经办人", "remark": "备注", "source_sequence": "序号"}


def issue(record: dict, code: str, field: str, severity: str, message: str) -> None:
    record["issues"].append({"code": code, "field": field, "severity": severity, "message": message})


def value(record: dict, header: str):
    return record["raw_values"].get(header, {}).get("value")


def text(value) -> str | None:
    return str(value).strip() or None if value is not None else None


def number(record: dict, header: str, required: bool) -> str | None:
    raw = value(record, header)
    if raw is None or str(raw).strip() == "":
        issue(record, "missing_number", header, "error" if required else "warning", f"{header}为空")
        return None
    try:
        if isinstance(raw, bool):
            raise ValueError()
        n = Decimal(str(raw).strip().replace(",", "").replace("，", ""))
        if not n.is_finite() or n < 0:
            raise ValueError()
        return format(n, "f")
    except (InvalidOperation, ValueError):
        issue(record, "invalid_number", header, "error" if required else "warning", f"{header}必须为有限非负数")
        return None


def parse_date(raw, epoch: datetime) -> str:
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        parsed = from_excel(raw, epoch)
        if isinstance(parsed, datetime):
            return parsed.date().isoformat()
        raise ValueError("date serial is time-only")
    t = str(raw).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(t, fmt).date().isoformat()
        except ValueError:
            pass
    return datetime.fromisoformat(t).date().isoformat()


def normalize_movements(records: list[dict], source: dict) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    events, exact_seen, business_seen = [], {}, {}
    by_material = defaultdict(list)
    epoch = datetime.fromisoformat(source["excel_epoch"])
    for record in records:
        n = {key: text(value(record, header)) for key, header in TEXT_FIELDS.items()}
        # Preserve formatted numeric identifiers, including significant leading zeros.
        code_cell = record["raw_values"].get("物料编码", {})
        if isinstance(code_cell.get("value"), (int, float)):
            raw_code = code_cell["value"]
            if float(raw_code).is_integer():
                n["material_code"] = str(int(raw_code))
                fmt = code_cell.get("number_format", "")
                if re.fullmatch(r"0+", fmt):
                    n["material_code"] = n["material_code"].zfill(len(fmt))
        for key in ("material_code", "material_name", "unit"):
            if not n[key]:
                issue(record, "missing_field", TEXT_FIELDS[key], "error", f"{TEXT_FIELDS[key]}为空")
        try:
            n["transaction_date"] = parse_date(value(record, "交易日期"), epoch)
        except (ValueError, TypeError, OverflowError):
            n["transaction_date"] = None
            issue(record, "invalid_date", "交易日期", "error", "非法交易日期")
        raw_type = str(value(record, "交易类型")).strip().lower()
        n["transaction_type"] = "inbound" if raw_type in INBOUND else "outbound" if raw_type in OUTBOUND else None
        if n["transaction_type"] is None:
            issue(record, "invalid_type", "交易类型", "error", "无法识别交易类型")
        n["quantity"] = number(record, "数量", True)
        n["amount"] = number(record, "金额（元）", False)
        n["unit_price"] = number(record, "单价（元）", False)
        if not n["supplier"]:
            issue(record, "missing_supplier", "供应商名称", "warning", "未提供供应商")
        for header, cell in record["raw_values"].items():
            if cell.get("type") in {"f", "e"}:
                severity = "error" if header in {"物料编码", "物料名称", "单位", "交易日期", "交易类型", "数量"} else "warning"
                issue(record, "unevaluated_cell", header, severity, "公式或错误单元格未被静默解释为事实")
        record["normalized_values"] = n
        if any(i["severity"] == "error" for i in record["issues"]):
            record["status"] = "invalid"
            continue
        fingerprint = digest({h: c["value"] for h, c in record["raw_values"].items()})
        if n["source_sequence"] is not None and fingerprint in exact_seen:
            record["status"] = "duplicate"
            record["duplicate_of"] = exact_seen[fingerprint]
            issue(record, "exact_duplicate", "*", "warning", "包括序号的整行完全重复，保留证据但不重复计数")
            continue
        exact_seen[fingerprint] = record["source_record_id"]
        business_key = digest({k: v for k, v in n.items() if k != "source_sequence"})
        if business_key in business_seen:
            issue(record, "possible_duplicate", "*", "warning", "业务字段相同但非整行重复，仍作为独立事件计数")
        business_seen[business_key] = record["source_record_id"]
        record["status"] = "valid"
        event = {**n, "movement_id": record["source_record_id"].replace("source/", "movement/"),
                 "source_record_id": record["source_record_id"], "excel_row": record["excel_row"]}
        for key in ("department", "supplier"):
            event[key + "_id"] = key + "/" + digest(n[key]) if n[key] else None
        events.append(event)
        by_material[n["material_code"]].append(event)

    materials = []
    by_source = {r["source_record_id"]: r for r in records}
    for code, movements in sorted(by_material.items()):
        latest = max(movements, key=lambda e: (e["transaction_date"], e["excel_row"]))
        meta = {k: latest[k] for k in ("material_code", "material_name", "material_specification", "material_category", "unit")}
        conflicts = {k: sorted({e[k] for e in movements if e[k] is not None})
                     for k in ("material_name", "material_specification", "material_category", "unit")}
        conflicts = {k: v for k, v in conflicts.items() if len(v) > 1}
        if conflicts:
            for event in movements:
                issue(by_source[event["source_record_id"]], "material_metadata_conflict", ",".join(conflicts),
                      "warning", "同一物料编码出现不同主数据属性；仅按编码归组，显示属性取观察日前末次记录")
        materials.append({"material_id": "material/" + code, **meta, "metadata_conflicts": conflicts,
                          "metadata_source_record_id": latest["source_record_id"]})
    entities = {}
    for kind in ("department", "supplier"):
        entities[kind] = sorted({(e[kind + "_id"], e[kind]) for e in events if e[kind]})
    return materials, events, [{"department_id": i, "name": n} for i, n in entities["department"]], [{"supplier_id": i, "name": n} for i, n in entities["supplier"]]
