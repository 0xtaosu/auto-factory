from datetime import date, timedelta
from io import BytesIO
from pathlib import Path

import pytest
from openpyxl import Workbook
from rdflib import Graph, RDF

from app.inventory_activity.common import ActivityError, defaults
from app.inventory_activity.export_rdf import ASSESSMENT, INV, METRIC, PROV, build_graph, resource
from app.inventory_activity.export_results import export_results
from app.inventory_activity.load_erp import HEADERS, SHEET_NAME
from app.inventory_activity.pipeline import analyze_workbook, explain

ROOT = Path(__file__).resolve().parents[2]
OBS = date(2025, 12, 31)


def row(code="A", days=0, direction="出库", sequence=1, **changes):
    values = {"序号": sequence, "物料编码": code, "物料名称": "测试物料", "物料规格": "型号 A",
              "物料类别": "标准件", "交易日期": OBS - timedelta(days=days), "交易类型": direction,
              "单位": "件", "数量": "12.50", "单价（元）": "2.00", "金额（元）": "25.00",
              "出入库部门": "生产部", "经办人": "测试", "供应商名称": "供应商 A", "备注": "测试流水"}
    return {**values, **changes}


def workbook(*rows, headers=None):
    wb = Workbook()
    ws = wb.active
    ws.title = SHEET_NAME
    headers = headers or HEADERS
    ws.append(headers)
    for values in rows:
        ws.append([values.get(h) for h in headers])
    buffer = BytesIO()
    wb.save(buffer)
    wb.close()
    return buffer.getvalue()


def run(*rows, **kwargs):
    return analyze_workbook(workbook(*rows), "test.xlsx", **kwargs)


@pytest.mark.parametrize("days,candidate", [(0, False), (12, False), (179, False), (180, True), (181, True)])
def test_days_boundary_and_dec31(days, candidate):
    result = run(row(days=days))
    a = result["activity_assessments"][0]
    assert a["days_since_last_movement"] == days
    assert a["inactive_candidate"] is candidate
    assert a["movement_frequency"] == 1
    assert a["annual_outbound_quantity"] == "12.50"


@pytest.mark.parametrize("direction,quantity", [("入库", "0"), ("出库", "12.50")])
def test_single_direction_and_no_stock_assumption(direction, quantity):
    result = run(row(direction=direction, days=181))
    a = result["activity_assessments"][0]
    assert a["inactive_candidate"] is True
    assert a["annual_outbound_quantity"] == quantity
    assert "current_on_hand" not in a
    assert "obsolete_inventory" not in a


def test_recent_inbound_overrides_old_outbound():
    a = run(row(days=200), row(days=1, direction="入库", sequence=2))["activity_assessments"][0]
    assert a["days_since_last_movement"] == 1
    assert a["inactive_candidate"] is False


def test_identical_rows_without_source_sequence_are_not_silently_collapsed():
    first = row(**{"序号": None})
    result = run(first, first)
    assert len(result["movement_events"]) == 2
    assert result["overview"]["counts"]["duplicate_count"] == 0
    assert any(i["code"] == "possible_duplicate" for i in result["source_records"][1]["issues"])


def test_same_day_events_and_exact_duplicate_vs_possible_duplicate():
    first = row(days=180)
    result = run(first, first, row(days=180, sequence=2))
    c = result["overview"]["counts"]
    assert (c["total_records"], c["valid_records"], c["duplicate_count"]) == (3, 2, 1)
    a = result["activity_assessments"][0]
    assert a["movement_frequency"] == 2
    assert len(a["last_movement_event_ids"]) == 2
    assert a["annual_outbound_quantity"] == "25.00"
    duplicate = result["source_records"][1]
    assert duplicate["duplicate_of"] == result["source_records"][0]["source_record_id"]
    assert result["source_records"][2]["issues"][0]["code"] == "possible_duplicate"


@pytest.mark.parametrize("field,value", [("物料编码", None), ("交易日期", "2025-02-30"), ("交易类型", "未知"),
                                         ("数量", -1), ("数量", "NaN"), ("数量", "Infinity"), ("数量", True), ("单位", None)])
def test_invalid_rows_preserve_raw_evidence(field, value):
    result = run(row(**{field: value}))
    assert result["overview"]["counts"]["invalid_records"] == 1
    assert result["movement_events"] == []
    assert result["source_records"][0]["raw_values"][field]["value"] == value
    assert result["overview"]["days_since_last_movement"]["min"] is None


@pytest.mark.parametrize("amount", [None, "", -1, "NaN", "Infinity", "=SUM(A1:A2)"])
def test_missing_or_bad_optional_amount_does_not_hide_movement(amount):
    result = run(row(**{"金额（元）": amount, "供应商名称": None}))
    a = result["activity_assessments"][0]
    assert a["days_since_last_movement"] == 0
    assert a["annual_outbound_quantity"] == "12.50"
    assert a["annual_outbound_value"] is None
    assert result["suppliers"] == []
    assert result["source_records"][0]["issues"]


def test_formula_in_critical_field_is_not_an_identity():
    result = run(row(**{"物料编码": '=A1'}))
    assert not result["materials"]


def test_normalization_raw_values_decimal_and_date():
    result = run(row(code=" 001 ", **{"交易日期": "2025/12/31", "数量": "1,234.50", "金额（元）": "2,469.00"}))
    assert result["materials"][0]["material_code"] == "001"
    assert result["activity_assessments"][0]["annual_outbound_quantity"] == "1234.50"
    assert result["source_records"][0]["raw_values"]["物料编码"]["value"] == " 001 "


def test_future_event_is_retained_but_not_used():
    result = run(row(days=181), row(days=0, sequence=2), settings={"observation_date": "2025-12-30", "frequency_window_end": "2025-12-30"})
    assert len(result["movement_events"]) == 2
    a = result["activity_assessments"][0]
    assert a["days_since_last_movement"] == 180
    assert a["movement_frequency"] == 1
    assert a["inactive_candidate"] is True
    assert result["overview"]["counts"]["future_event_count"] == 1


def test_future_only_is_unknown_not_active_or_365_zero():
    result = run(row(), settings={"observation_date": "2025-12-30", "frequency_window_end": "2025-12-30"})
    a = result["activity_assessments"][0]
    assert a["inactive_candidate"] is None
    assert a["classification"] == "NotEvaluated"
    assert a["days_since_last_movement"] is None
    assert any("365" in text for text in result["overview"]["limitations"])


def test_outside_coverage_observation_rejected():
    with pytest.raises(ActivityError, match="覆盖窗口"):
        run(row(), settings={"observation_date": "2026-01-01"})


def test_unit_conflict_blocks_quantity_but_not_frequency():
    result = run(row(), row(sequence=2, **{"单位": "千件"}))
    a = result["activity_assessments"][0]
    assert a["movement_frequency"] == 2
    assert a["annual_outbound_quantity"] is None
    assert result["materials"][0]["metadata_conflicts"]["unit"] == ["件", "千件"]
    assert a["annual_outbound_quantity_by_unit"] == {"件": "12.50", "千件": "12.50"}
    assert result["overview"]["counts"]["anomaly_record_count"] == 2


def test_policy_configuration_snapshot_and_determinism():
    content = workbook(row(days=179))
    default = analyze_workbook(content, "test.xlsx")
    repeated = analyze_workbook(content, "test.xlsx")
    policy = defaults()["policy"]
    policy["threshold_value"] = 179
    changed = analyze_workbook(content, "test.xlsx", policy=policy)
    assert default == repeated
    assert default["movement_events"] == changed["movement_events"]
    assert default["policy"]["policy_snapshot_id"] != changed["policy"]["policy_snapshot_id"]
    assert default["run"]["run_id"] != changed["run"]["run_id"]
    assert default["activity_assessments"][0]["inactive_candidate"] is False
    assert changed["activity_assessments"][0]["inactive_candidate"] is True


@pytest.mark.parametrize("change", [{"effective_from": "2026-01-01"}, {"effective_to": "2025-06-01"}, {"material_category": "备件"}])
def test_inapplicable_policy_is_not_active(change):
    result = run(row(days=181), policy={**defaults()["policy"], **change})
    assert result["activity_assessments"][0]["inactive_candidate"] is None


@pytest.mark.parametrize("change", [{"threshold_value": -1}, {"threshold_value": True}, {"operator": ">"}, {"metric": "ITR"}])
def test_invalid_policy_rejected(change):
    with pytest.raises(ActivityError):
        run(row(), policy={**defaults()["policy"], **change})


def test_metric_windows_are_separate():
    result = run(row(days=180), row(days=0, sequence=2), settings={"frequency_window_start": "2025-12-01"})
    a = result["activity_assessments"][0]
    assert a["movement_frequency"] == 1
    assert a["annual_outbound_quantity"] == "25.00"


def test_explanation_rdf_queries_and_exports(tmp_path):
    result = run(row(code="GC010", days=180), row(code="B", days=0, sequence=2))
    export_results(result, tmp_path)
    graph = Graph().parse(tmp_path / "inventory-activity.ttl", format="turtle")
    assert len(list(graph.subjects(RDF.type, INV.Material))) == 2
    assert len(list(graph.subjects(RDF.type, INV.InventoryMovementEvent))) == 2
    assert len(list(graph.subjects(RDF.type, METRIC.MetricObservation))) == 20
    query_results = {p.name: list(graph.query(p.read_text())) for p in (ROOT / "queries").glob("*.rq")}
    assert len(query_results["inactive-materials.rq"]) == 1
    assert len(query_results["last-movement.rq"]) == 1
    assert len(query_results["assessment-policy.rq"]) == 2
    assert len(query_results["explain-candidate.rq"]) == 1
    detail = explain(result, "GC010")
    assert "180" in detail["explanation"]
    assert detail["source_records"][0]["excel_row"] == 2
    assessment = resource(detail["assessment"]["assessment_id"])
    metrics = list(graph.objects(assessment, ASSESSMENT.usesObservation))
    assert len(metrics) == 10
    recency = resource(detail["assessment"]["metric_observation_ids"][0])
    event = next(graph.objects(recency, METRIC.lastMovementEvent))
    source = next(graph.objects(event, PROV.wasDerivedFrom))
    assert str(next(graph.objects(source, INV.excelRow))) == "2"
    assert (tmp_path / "activity_assessments.csv").read_text(encoding="utf-8-sig").count("GC010") >= 1
    assert "Existing Design" in (tmp_path / "inventory-activity-mvp.md").read_text()


def test_missing_sheet_or_headers():
    with pytest.raises(ActivityError, match="关键字段"):
        analyze_workbook(workbook(row(), headers=["物料编码"]), "bad.xlsx")
    with pytest.raises(ActivityError, match="Excel"):
        analyze_workbook(b"invalid xlsx", "bad.xlsx")


def test_real_erp_baseline_and_provenance():
    path = ROOT / "PRD/01-原始数据模板/机械装备企业ERP报表_4亿产值.xlsx"
    result = analyze_workbook(path.read_bytes(), path.name)
    counts = result["overview"]["counts"]
    assert (counts["valid_records"], counts["material_count"], counts["inbound_count"], counts["outbound_count"], counts["ge_180_count"]) == (12794, 820, 5194, 7600, 13)
    assert counts["ge_90_count"] == 73
    assert counts["quantity_unavailable_count"] == 531
    assert len({e["movement_id"] for e in result["movement_events"]}) == 12794
    sources = {r["source_record_id"] for r in result["source_records"]}
    assert all(e["source_record_id"] in sources for e in result["movement_events"])
    gc = explain(result, "GC010")
    assert gc["assessment"]["last_movement_date"] == "2025-12-08"
    assert gc["assessment"]["days_since_last_movement"] == 23
    assert gc["assessment"]["inactive_candidate"] is False
    assert all(row["diff"] == 0 for row in result["overview"]["baseline_comparison"])
