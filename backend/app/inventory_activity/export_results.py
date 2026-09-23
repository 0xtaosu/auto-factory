from __future__ import annotations

import csv
from pathlib import Path

from .common import dumps
from .export_rdf import export_rdf
from .pipeline import explain

COLLECTIONS = ("materials", "movement_events", "metric_observations", "activity_assessments",
               "departments", "suppliers", "source_records")


def csv_value(value):
    if isinstance(value, (dict, list)):
        return dumps(value, sort_keys=True)
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value  # Spreadsheet formula injection protection; JSON preserves exact text.
    return value


def export_csv(rows: list[dict], path: Path) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        headers = list(dict.fromkeys(k for row in rows for k in row))
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows({k: csv_value(v) for k, v in row.items()} for row in rows)


def md(value) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def render_report(result: dict) -> str:
    run, overview, quality = result["run"], result["overview"], result["data_quality"]
    lines = ["# 库存物料活跃度 MVP 数据质量与验收报告", "",
             f"源文件：{md(run['source_filename'])}  ", f"工作表：{md(run['sheet_name'])}  ",
             f"源文件 SHA256：`{run['source_file_sha256']}`  ", f"运行标识：`{run['run_id']}`  ",
             f"观察日：{run['observation_date']}  ",
             f"声明的数据覆盖窗口：{run['data_window_start']} ～ {run['data_window_end']}  ",
             f"实际有效事件日期：{quality['actual_event_date_start']} ～ {quality['actual_event_date_end']}  ",
             f"频率统计窗口：{run['frequency_window_start']} ～ {run['frequency_window_end']}  ",
             f"策略：{md(result['policy']['policy_id'])}，DaysSinceLastMovement >= {result['policy']['threshold_value']} 天。", "",
             "## 数据质量", "", "| 项目 | ACTUAL |", "|---|---:|"]
    labels = {"total_records": "总流水数", "valid_records": "有效流水数（去除明确重复后）", "invalid_records": "无效流水数",
              "duplicate_count": "整行重复数量", "anomaly_record_count": "存在错误或警告的原始行数", "material_count": "Material 数量",
              "inbound_count": "入库笔数", "outbound_count": "出库笔数", "inactive_candidate_count": "当前策略候选数量",
              "ge_90_count": ">=90 天 Material 数", "ge_180_count": ">=180 天 Material 数",
              "future_event_count": "观察日后事件数", "outside_data_window_count": "声明覆盖窗口外事件数",
              "not_evaluated_count": "无法评估/策略不适用物料数", "material_metadata_conflict_count": "主数据属性冲突物料数",
              "quantity_unavailable_count": "年度出库数量总量不可用物料数（单位冲突）"}
    lines += [f"| {label} | {quality[k]} |" for k, label in labels.items()]
    lines += ["", "主数据冲突按物料编码保留原始事实，显示名称/规格取观察日前末次记录，不代表完成主数据清洗。",
              "单位冲突时 AnnualOutboundQuantity 为 null，并提供 annual_outbound_quantity_by_unit；在获得换算关系或纠正主数据前，不能声称所有物料数量合计已可用。"]
    lines += ["", "总流水数 = 有效流水数 + 无效流水数 + 明确重复数。异常记录数可能与这三类重叠。",
              "原始行全部保留，金额缺失不补零；金额类指标不可用时输出 null。CSV 对公式起始文本添加单引号，精确原值见 JSON/RDF。",
              "", "## 末次动用天数分布", "", "分位数使用线性插值 `(n-1)*p`。", "", "| 统计 | 天数 |", "|---|---:|"]
    lines += [f"| {k} | {v if v is not None else '不可用'} |" for k, v in overview["days_since_last_movement"].items()]
    lines += ["", "## Review 基线交叉检查", "", "基线只作对照，不作为数据过滤条件或强制断言。", "",
              "| 指标 | EXPECTED | ACTUAL | DIFF | 原因 |", "|---|---:|---:|---:|---|"]
    lines += [f"| {r['metric']} | {r['expected']} | {r['actual']} | {r['diff']} | {md(r['reason'])} |" for r in overview["baseline_comparison"]]
    lines += ["", "## Existing Design / Conflict / Proposed Resolution", "",
              "| Existing Design | Conflict | Proposed Resolution |", "|---|---|---|",
              "| 入库金额减出库金额被称为库存总资金 | 无期初/期末快照，净流量不等于库存 | 新链路只输出活动指标，不重建余额 |",
              "| 最后出库日 + 净金额 + 只有入库即疑似呆滞 | 与末次任意动用和候选语义不一致 | 独立 DaysSinceLastMovement 和配置策略 |",
              "| 只保存任务汇总，原始 Excel 不保存 | 缺少原始行证据链 | 保存源文件、行快照、事件和全部指标证据 |",
              "| LLM 生成健康结论 | 超出确定性诊断范围 | MVP API 不调用 LLM，解释由证据生成 |",
              "| 未发现现有 ontology、46 个冻结 L1 或完整指标图谱 | 无法核实外部编号定义 | 仅保留 M6-01-02 的诊断支持关系，不声明 ITR 等价或子类 |",
              "", "## 本体对齐", "",
              "IOF 仅使用 `rdfs:seeAlso` 参考 MaterialLocationChangeProcess，不推断 ERP 记录满足全部物理过程公理，不导入 APS。",
              "参考：[IOF Release 202502](https://spec.industrialontologies.org/portal/release/202502/core/MaterialLocationChangeProcess.html)。",
              "`https://example.org/` 是本 MVP 的应用命名空间，部署到企业图谱时可统一迁移；不声称它是现有冻结指标图谱的正式 IRI。",
              "", "## 观察边界", ""]
    lines += [f"- {v}" for v in overview["limitations"]]
    lines += ["", "## 候选与追溯示例", ""]
    candidates = [a for a in result["activity_assessments"] if a["inactive_candidate"] is True]
    for assessment in candidates[:3]:
        detail = explain(result, assessment["material_code"])
        lines += [detail["explanation"], ""]
        for record in detail["source_records"]:
            lines += [f"- `{record['source_record_id']}`，Excel 第 {record['excel_row']} 行。"]
        lines.append("")
    if not candidates:
        lines += ["本次已观察且可评估物料中没有命中当前策略的候选；不代表未观测物料或库存健康。", ""]
    gc = next((a for a in result["activity_assessments"] if a["material_code"] == "GC010"), None)
    if gc:
        lines += [explain(result, "GC010")["explanation"], "需求中的 217 天案例是示意，不覆盖真实数据。", ""]
    lines += ["## 复核入口", "", "- `source_records.jsonl`：逐行 raw/normalized 值、状态、错误/警告与去重关系。",
              "- `movement_events.jsonl`：每个有效交易的独立事件及来源。",
              "- `metric_observations.jsonl`：统计窗口、数值、单位、全部参与事件。",
              "- `activity_assessments.csv`：候选清单与阈值，便于人工验算。",
              "- `inventory-activity.ttl`：完整本体和实例；`queries/` 提供四类 SPARQL 验收查询。",
              "- `manifest.json` 和 `policy.json`：输入指纹、运行配置、策略快照。", ""]
    return "\n".join(lines)


def export_results(result: dict, output_dir: Path, report_path: Path | None = None) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for name in COLLECTIONS:
        rows = result[name]
        (output_dir / f"{name}.json").write_text(dumps(rows), encoding="utf-8")
        with (output_dir / f"{name}.jsonl").open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(dumps(row) + "\n")
        export_csv(rows, output_dir / f"{name}.csv")
    for name, value in (("result", result), ("overview", result["overview"]), ("manifest", result["run"]), ("policy", result["policy"]), ("data_quality", result["data_quality"])):
        (output_dir / f"{name}.json").write_text(dumps(value), encoding="utf-8")
    export_rdf(result, output_dir / "inventory-activity.ttl")
    report = render_report(result)
    (output_dir / "inventory-activity-mvp.md").write_text(report, encoding="utf-8")
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report, encoding="utf-8")
