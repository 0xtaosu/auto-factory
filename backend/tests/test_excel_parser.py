from pathlib import Path

from app.excel_parser import parse_workbook


def test_parse_sample_workbook():
    workbook = Path(__file__).resolve().parents[2] / "PRD" / "01-原始数据模板" / "机械装备企业ERP报表_4亿产值.xlsx"
    transactions, quality = parse_workbook(workbook.read_bytes())

    assert len(transactions) > 1000
    assert quality["sheet_name"]
    assert quality["quality_grade"] in {"A", "B", "C"}
    assert {"入库", "出库"}.issubset({tx.trans_type for tx in transactions})
