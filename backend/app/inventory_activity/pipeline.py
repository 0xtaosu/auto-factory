from __future__ import annotations

from copy import deepcopy
from datetime import date

from .calculate_activity_metrics import calculate_activity_metrics
from .common import ActivityError, SCHEMA_VERSION, defaults, digest, iso_date
from .evaluate_slow_moving import evaluate_slow_moving, validate_policy
from .load_erp import load_erp
from .normalize_movements import issue, normalize_movements

LIMITATIONS = [
    "候选仅表示达到无交易天数阈值；缺少当前库存余额，不能据此确认存在库存或判断库存健康。",
    "左截断：本数据只覆盖给定窗口，全年无流水的物料可能未出现；365 天以上状态无法完整观测。",
    "同日交易缺少时间戳，末次日期并列的事件全部保留；展示行号顺序不代表业务发生先后。",
    "指标只基于通过校验的事件；被拒绝的记录可能影响完整性，请结合数据质量明细复核。",
    "同一编码的主数据冲突保留并警告；数量单位不一致时不跨单位相加，按单位分别提供数量。",
]


def percentile(values: list[int], p: float):
    if not values:
        return None
    ordered = sorted(values)
    pos = (len(ordered) - 1) * p
    lo = int(pos)
    return round(ordered[lo] + (ordered[min(lo + 1, len(ordered) - 1)] - ordered[lo]) * (pos - lo), 2)


def analyze_workbook(content: bytes, filename: str, settings: dict | None = None, policy: dict | None = None) -> dict:
    config = deepcopy(defaults())
    selected_policy = validate_policy(deepcopy(policy if policy is not None else config.pop("policy")))
    config.pop("policy", None)
    config.update(settings or {})
    for field in ("observation_date", "data_window_start", "data_window_end", "frequency_window_start", "frequency_window_end"):
        config[field] = iso_date(config[field], field).isoformat()
    if not config["data_window_start"] <= config["observation_date"] <= config["data_window_end"]:
        raise ActivityError("观察日必须位于声明的数据覆盖窗口内，不能假定窗口以外没有交易")
    if not config["data_window_start"] <= config["frequency_window_start"] <= config["frequency_window_end"] <= config["observation_date"]:
        raise ActivityError("频率窗口必须位于数据覆盖范围内且不晚于观察日")
    records, source = load_erp(content, filename)
    materials, events, departments, suppliers = normalize_movements(records, source)
    # Valid events outside declared coverage are preserved, but excluded from this run.
    indexed = {r["source_record_id"]: r for r in records}
    included = []
    for event in events:
        if not config["data_window_start"] <= event["transaction_date"] <= config["data_window_end"]:
            issue(indexed[event["source_record_id"]], "outside_data_window", "交易日期", "warning", "事件在声明覆盖窗口外，不参与本次计算")
        else:
            included.append(event)
    run = {**config, **source, "schema_version": SCHEMA_VERSION,
           "run_id": digest([SCHEMA_VERSION, source["source_file_sha256"], config, selected_policy])}
    observations, summaries = calculate_activity_metrics(materials, included, run)
    assessments = evaluate_slow_moving(materials, summaries, run, selected_policy)
    days = [a["days_since_last_movement"] for a in assessments if a["days_since_last_movement"] is not None]
    counts = {
        "total_records": len(records), "valid_records": len(events),
        "invalid_records": sum(r["status"] == "invalid" for r in records),
        "duplicate_count": sum(r["status"] == "duplicate" for r in records),
        "anomaly_record_count": sum(bool(r["issues"]) for r in records),
        "material_count": len(materials), "inbound_count": sum(e["transaction_type"] == "inbound" for e in events),
        "outbound_count": sum(e["transaction_type"] == "outbound" for e in events),
        "inactive_candidate_count": sum(a["inactive_candidate"] is True for a in assessments),
        "ge_90_count": sum(d >= 90 for d in days), "ge_180_count": sum(d >= 180 for d in days),
        "not_evaluated_count": sum(a["inactive_candidate"] is None for a in assessments),
        "future_event_count": sum(e["transaction_date"] > run["observation_date"] for e in included),
        "outside_data_window_count": len(events) - len(included),
        "material_metadata_conflict_count": sum(bool(m["metadata_conflicts"]) for m in materials),
        "quantity_unavailable_count": sum(a["annual_outbound_quantity"] is None for a in assessments),
    }
    stats = {"min": min(days) if days else None, "median": percentile(days, .5),
             "p75": percentile(days, .75), "p90": percentile(days, .9), "max": max(days) if days else None}
    baselines = {"total_records": 12794, "material_count": 820, "inbound_count": 5194, "outbound_count": 7600, "ge_180_count": 13}
    baseline_comparison = []
    for key, expected in baselines.items():
        diff = counts[key] - expected
        reason = "与 Review 基线一致" if diff == 0 else (
            f"本次输入 {source['source_file_sha256'][:12]}；观察日 {run['observation_date']}；"
            f"无效 {counts['invalid_records']} 行、整行重复 {counts['duplicate_count']} 行、"
            f"窗口外 {counts['outside_data_window_count']} 笔、观察日后 {counts['future_event_count']} 笔。"
            "该基线只适用于原始 2025 ERP 包；逐行原因见 source_records，不强制对齐。")
        baseline_comparison.append({"metric": key, "expected": expected, "actual": counts[key], "diff": diff, "reason": reason})
    dates = [e["transaction_date"] for e in events]
    quality = {**counts, "actual_event_date_start": min(dates) if dates else None,
               "actual_event_date_end": max(dates) if dates else None,
               "count_reconciliation": "total_records = valid_records + invalid_records + duplicate_count",
               "issues": [{"source_record_id": r["source_record_id"], "excel_row": r["excel_row"], "issues": r["issues"]} for r in records if r["issues"]],
               "material_conflicts": [m for m in materials if m["metadata_conflicts"]]}
    overview = {**{k: run[k] for k in config}, "policy": selected_policy, "counts": counts,
                "days_since_last_movement": stats, "limitations": LIMITATIONS,
                "baseline_comparison": baseline_comparison}
    return {"run": run, "policy": selected_policy, "overview": overview, "data_quality": quality,
            "materials": materials, "movement_events": events, "departments": departments, "suppliers": suppliers,
            "source_records": records, "metric_observations": observations, "activity_assessments": assessments}


def explain(result: dict, material_code: str) -> dict:
    assessment = next((a for a in result["activity_assessments"] if a["material_code"] == material_code), None)
    if assessment is None:
        raise KeyError(material_code)
    events = [e for e in result["movement_events"] if e["movement_id"] in assessment["last_movement_event_ids"]]
    sources = {e["source_record_id"] for e in events}
    candidate = assessment["inactive_candidate"]
    policy = result["policy"]
    if candidate is None:
        description = f"{material_code} 未完成判断：{assessment['evaluation_status']}。"
    else:
        verdict = "达到阈值，列为长期无交易物料候选" if candidate else "未达到阈值，不列为长期无交易物料候选"
        description = (f"{material_code} 最后交易日期 {assessment['last_movement_date']}，"
                       f"截至 {assessment['observation_date']} 为 {assessment['days_since_last_movement']} 天。"
                       f"策略 {policy['policy_id']} 使用 >= {policy['threshold_value']} 天，{verdict}。")
    return {"assessment": assessment, "policy": policy,
            "metric_observations": [o for o in result["metric_observations"] if o["material_code"] == material_code],
            "last_movement_events": events, "source_records": [r for r in result["source_records"] if r["source_record_id"] in sources],
            "explanation": description, "limitations": LIMITATIONS}
