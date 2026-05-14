from datetime import date, timedelta

from app.analysis import analyze
from app.models import Transaction


def test_analyze_unhealthy_inventory():
    transactions = []
    start = date(2025, 1, 1)
    for month in range(12):
        current = start + timedelta(days=month * 30)
        for index in range(6):
            transactions.append(
                Transaction(
                    material_code=f"GC{index:03d}",
                    material_name=f"钢材{index}",
                    material_spec="12mm",
                    trans_date=current,
                    trans_type="入库",
                    quantity=100 + index,
                    amount=1_000_000 + index * 10_000,
                )
            )
        transactions.append(
            Transaction(
                material_code="GC000",
                material_name="钢材0",
                material_spec="12mm",
                trans_date=current,
                trans_type="出库",
                quantity=20,
                amount=200_000,
            )
        )

    data_quality = {
        "total_records": len(transactions),
        "valid_records": len(transactions),
        "invalid_records": 0,
        "quality_grade": "A",
        "date_range": {"start_date": "2025-01-01", "end_date": "2025-12-01"},
        "material_count": 6,
    }
    overview, details = analyze(transactions, data_quality)

    assert overview["overall_health"]["grade"] == "red"
    assert details["balance"]["traffic_light"] == "red"
    assert details["stagnant_ratio"]["count"] >= 5
