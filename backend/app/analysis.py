from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
from statistics import mean
from typing import Any

from .models import Transaction


DEFAULT_CONFIG = {
    "stagnant_days": 180,
    "price_deviation": 0.5,
    "qty_deviation": 1.0,
    "min_history_records": 3,
    "top_count": 10,
}


def analyze(transactions: list[Transaction], data_quality: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    total_value = calc_total_value(transactions)
    stagnant = calc_stagnant_ratio(transactions)
    balance = calc_balance_ratio(transactions)
    anomalies = detect_anomalies(transactions)

    details = {
        "total_value": total_value,
        "stagnant_ratio": stagnant,
        "balance": balance,
        "anomalies": anomalies,
    }
    overview = build_overview(details, data_quality)
    return overview, details


def calc_total_value(transactions: list[Transaction]) -> dict[str, Any]:
    monthly = defaultdict(lambda: {"in_amount": 0.0, "out_amount": 0.0})
    total_in = 0.0
    total_out = 0.0

    for tx in sorted(transactions, key=lambda item: item.trans_date):
        month = tx.trans_date.strftime("%Y-%m")
        if tx.trans_type == "入库":
            total_in += tx.amount
            monthly[month]["in_amount"] += tx.amount
        else:
            total_out += tx.amount
            monthly[month]["out_amount"] += tx.amount

    monthly_trend = []
    for month, values in sorted(monthly.items()):
        monthly_trend.append(
            {
                "month": month,
                "in_amount": round(values["in_amount"], 2),
                "out_amount": round(values["out_amount"], 2),
                "net_change": round(values["in_amount"] - values["out_amount"], 2),
            }
        )

    trend_direction = "数据不足"
    if len(monthly_trend) >= 6:
        last_3 = monthly_trend[-3:]
        prev_3 = monthly_trend[-6:-3]
        avg_last = mean(item["net_change"] for item in last_3)
        avg_prev = mean(item["net_change"] for item in prev_3)
        if avg_last <= 0:
            trend_direction = "下降"
        elif avg_last > avg_prev * 1.1:
            trend_direction = "快速上升"
        elif avg_last > avg_prev:
            trend_direction = "缓慢上升"
        else:
            trend_direction = "平稳"
    elif len(monthly_trend) >= 3:
        avg_last = mean(item["net_change"] for item in monthly_trend[-3:])
        trend_direction = "下降" if avg_last <= 0 else "缓慢上升"

    total = total_in - total_out
    return {
        "indicator_id": "total_value",
        "title": "库存总资金月度趋势",
        "total_value": round(total, 2),
        "total_in": round(total_in, 2),
        "total_out": round(total_out, 2),
        "display_value": format_money(total),
        "monthly": monthly_trend[-12:],
        "trend_direction": trend_direction,
        "traffic_light": traffic_for_total_value(trend_direction),
        "trend_analysis": summarize_total_value(total, trend_direction),
    }


def calc_stagnant_ratio(transactions: list[Transaction]) -> dict[str, Any]:
    config_days = DEFAULT_CONFIG["stagnant_days"]
    base_date = max(tx.trans_date for tx in transactions)
    period_days = (base_date - min(tx.trans_date for tx in transactions)).days
    material_amount = defaultdict(float)
    material_meta: dict[str, Transaction] = {}
    last_out: dict[str, date] = {}

    for tx in transactions:
        material_meta.setdefault(tx.material_code, tx)
        if tx.trans_type == "入库":
            material_amount[tx.material_code] += tx.amount
        else:
            material_amount[tx.material_code] -= tx.amount
            if tx.material_code not in last_out or tx.trans_date > last_out[tx.material_code]:
                last_out[tx.material_code] = tx.trans_date

    total_amount = sum(material_amount.values())
    stagnant_items = []
    stagnant_amount = 0.0

    if period_days >= config_days:
        for code, amount in material_amount.items():
            meta = material_meta[code]
            if code in last_out:
                days_since = (base_date - last_out[code]).days
                is_stagnant = days_since >= config_days
                flag = None
            else:
                days_since = None
                is_stagnant = True
                flag = "only_inbound_no_outbound"

            if is_stagnant and amount > 0:
                stagnant_amount += amount
                stagnant_items.append(
                    {
                        "material_code": code,
                        "material_name": meta.material_name,
                        "material_spec": meta.material_spec,
                        "last_out_date": last_out.get(code).isoformat() if code in last_out else None,
                        "days_since_last_out": days_since,
                        "current_amount": round(amount, 2),
                        "display_amount": format_money(amount),
                        "flag": flag,
                    }
                )

    ratio = stagnant_amount / total_amount if total_amount > 0 else 0
    stagnant_items.sort(key=lambda item: item["current_amount"], reverse=True)
    for index, item in enumerate(stagnant_items, start=1):
        item["rank"] = index
        item["amount_pct"] = round(item["current_amount"] / total_amount * 100, 2) if total_amount > 0 else 0

    return {
        "indicator_id": "stagnant_ratio",
        "title": "呆滞物料分析",
        "config": {"stagnant_days": config_days, "green_ratio": 0.05, "yellow_ratio": 0.15},
        "ratio": round(ratio, 4),
        "display_value": f"{ratio:.1%}",
        "amount": round(stagnant_amount, 2),
        "display_amount": format_money(stagnant_amount),
        "count": len(stagnant_items),
        "analysis_date": base_date.isoformat(),
        "period_days": period_days,
        "traffic_light": traffic_for_stagnant(ratio),
        "top_list": stagnant_items[: DEFAULT_CONFIG["top_count"]],
        "summary": summarize_stagnant(ratio, stagnant_amount, len(stagnant_items)),
    }


def calc_balance_ratio(transactions: list[Transaction]) -> dict[str, Any]:
    monthly = defaultdict(lambda: {"in_amount": 0.0, "out_amount": 0.0})
    for tx in transactions:
        month = tx.trans_date.strftime("%Y-%m")
        if tx.trans_type == "入库":
            monthly[month]["in_amount"] += tx.amount
        else:
            monthly[month]["out_amount"] += tx.amount

    monthly_ratios = []
    for month, values in sorted(monthly.items()):
        out_amount = values["out_amount"]
        ratio = values["in_amount"] / out_amount if out_amount > 0 else None
        monthly_ratios.append(
            {
                "month": month,
                "in_amount": round(values["in_amount"], 2),
                "out_amount": round(out_amount, 2),
                "ratio": round(ratio, 2) if ratio is not None else None,
            }
        )

    valid = [item["ratio"] for item in monthly_ratios[-6:] if item["ratio"] is not None]
    if not valid:
        overall_ratio = None
        judgment = "数据不足"
    else:
        overall_ratio = round(mean(valid), 2)
        if len(valid) == 1:
            judgment = "数据不足，仅供参考"
        elif 0.8 <= overall_ratio <= 1.2:
            judgment = "平衡"
        elif overall_ratio <= 1.5:
            judgment = "轻微失衡"
        else:
            judgment = "严重失衡"

    return {
        "indicator_id": "balance",
        "title": "月度出入库对比",
        "overall_ratio": overall_ratio,
        "display_value": f"{overall_ratio:.2f}" if overall_ratio is not None else "--",
        "judgment": judgment,
        "traffic_light": traffic_for_balance(overall_ratio),
        "monthly": monthly_ratios[-12:],
        "analysis": summarize_balance(overall_ratio, judgment),
    }


def detect_anomalies(transactions: list[Transaction]) -> dict[str, Any]:
    in_transactions = [tx for tx in transactions if tx.trans_type == "入库" and tx.quantity > 0]
    out_counts = Counter(tx.material_code for tx in transactions if tx.trans_type == "出库")
    by_material: dict[str, list[Transaction]] = defaultdict(list)
    for tx in in_transactions:
        by_material[tx.material_code].append(tx)

    anomalies: list[dict[str, Any]] = []
    min_records = DEFAULT_CONFIG["min_history_records"]

    for code, tx_list in by_material.items():
        tx_list.sort(key=lambda item: item.trans_date)
        if len(tx_list) < min_records:
            continue

        latest = tx_list[-1]
        history = tx_list[:-1]
        avg_price = sum(tx.amount for tx in history) / sum(tx.quantity for tx in history) if sum(tx.quantity for tx in history) else 0
        latest_price = latest.amount / latest.quantity if latest.quantity else 0
        if avg_price > 0:
            deviation = abs(latest_price - avg_price) / avg_price
            if deviation >= DEFAULT_CONFIG["price_deviation"]:
                direction = "上涨" if latest_price > avg_price else "下跌"
                anomalies.append(
                    _anomaly_item(
                        latest,
                        "price_spike",
                        f"采购单价{direction}，偏离{deviation * 100:.0f}%",
                        latest.amount,
                        {"last_price": round(latest_price, 2), "avg_price": round(avg_price, 2), "deviation_ratio": round(deviation, 4)},
                    )
                )

        avg_qty = mean(tx.quantity for tx in history)
        if avg_qty > 0:
            qty_deviation = abs(latest.quantity - avg_qty) / avg_qty
            if qty_deviation >= DEFAULT_CONFIG["qty_deviation"]:
                anomalies.append(
                    _anomaly_item(
                        latest,
                        "qty_spike",
                        f"采购量异常，变化{qty_deviation * 100:.0f}%",
                        latest.amount,
                        {"last_quantity": latest.quantity, "avg_quantity": round(avg_qty, 2), "deviation_ratio": round(qty_deviation, 4)},
                    )
                )

        if out_counts.get(code, 0) <= 1:
            anomalies.append(
                _anomaly_item(
                    latest,
                    "no_outbound",
                    f"有入库但出库{out_counts.get(code, 0)}次，疑似已不再使用",
                    sum(tx.amount for tx in tx_list),
                )
            )

        if len(tx_list) >= min_records * 2:
            midpoint = len(tx_list) // 2
            first_half = tx_list[:midpoint]
            second_half = tx_list[midpoint:]
            first_days = max((first_half[-1].trans_date - first_half[0].trans_date).days, 1)
            second_days = max((second_half[-1].trans_date - second_half[0].trans_date).days, 1)
            first_freq = len(first_half) / first_days
            second_freq = len(second_half) / second_days
            freq_change = abs(second_freq - first_freq) / first_freq if first_freq > 0 else 0
            if freq_change >= 1.0:
                anomalies.append(
                    _anomaly_item(
                        latest,
                        "freq_change",
                        f"采购频率异常变化，期初vs期末变化{freq_change * 100:.0f}%",
                        sum(tx.amount for tx in tx_list[-3:]),
                        {"deviation_ratio": round(freq_change, 4)},
                    )
                )

    anomalies.sort(key=lambda item: item["last_amount"], reverse=True)
    anomaly_types = Counter(item["anomaly_type"] for item in anomalies)
    involved_amount = sum(item["last_amount"] for item in anomalies)
    return {
        "indicator_id": "anomalies",
        "title": "异常物料检测结果",
        "note": "自动检测结果，需人工确认",
        "total": len(anomalies),
        "involved_amount": round(involved_amount, 2),
        "display_amount": format_money(involved_amount),
        "breakdown": {
            "price_spike": anomaly_types.get("price_spike", 0),
            "qty_spike": anomaly_types.get("qty_spike", 0),
            "no_outbound": anomaly_types.get("no_outbound", 0),
            "freq_change": anomaly_types.get("freq_change", 0),
        },
        "traffic_light": traffic_for_anomalies(len(anomalies), involved_amount, transactions),
        "top_list": anomalies[: DEFAULT_CONFIG["top_count"]],
        "by_type": build_anomalies_by_type(anomalies),
        "summary": summarize_anomalies(len(anomalies), involved_amount),
    }


def build_overview(details: dict[str, Any], data_quality: dict[str, Any]) -> dict[str, Any]:
    indicators = [
        {
            "id": "total_value",
            "name": "库存总资金",
            "display_value": details["total_value"]["display_value"],
            "value": details["total_value"]["total_value"],
            "trend": details["total_value"]["trend_direction"],
            "traffic_light": details["total_value"]["traffic_light"],
            "summary": details["total_value"]["trend_analysis"],
        },
        {
            "id": "stagnant_ratio",
            "name": "呆滞物料占比",
            "display_value": details["stagnant_ratio"]["display_value"],
            "stagnant_amount": details["stagnant_ratio"]["amount"],
            "display_stagnant": details["stagnant_ratio"]["display_amount"],
            "traffic_light": details["stagnant_ratio"]["traffic_light"],
            "summary": details["stagnant_ratio"]["summary"],
        },
        {
            "id": "balance",
            "name": "出入库平衡度",
            "display_value": details["balance"]["display_value"],
            "judgment": details["balance"]["judgment"],
            "traffic_light": details["balance"]["traffic_light"],
            "summary": details["balance"]["analysis"],
        },
        {
            "id": "anomalies",
            "name": "异常物料检测",
            "total": details["anomalies"]["total"],
            "display_value": f"{details['anomalies']['total']}种",
            "involved_amount": details["anomalies"]["involved_amount"],
            "display_amount": details["anomalies"]["display_amount"],
            "traffic_light": details["anomalies"]["traffic_light"],
            "summary": details["anomalies"]["summary"],
        },
    ]
    grade = overall_grade(indicators)
    return {
        "overall_health": {
            "score": score_for_grade(grade),
            "grade": grade,
            "summary": overall_summary(indicators),
            "action_suggestions": action_suggestions(indicators),
        },
        "indicators": indicators,
        "data_quality": data_quality,
        "disclaimer": {
            "amount_basis": "库存金额基于采购进价/成本价计算，不含税",
            "stagnant_definition": "超过配置阈值天数无出库记录的物料",
            "anomaly_note": "异常检测为自动分析结果，仅供决策参考，需人工确认",
            "initial_stock": "不含期初结存，仅基于本周期交易数据",
        },
    }


def _anomaly_item(tx: Transaction, anomaly_type: str, desc: str, amount: float, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    item = {
        "material_code": tx.material_code,
        "material_name": tx.material_name,
        "material_spec": tx.material_spec,
        "anomaly_type": anomaly_type,
        "anomaly_desc": desc,
        "last_amount": round(amount, 2),
        "display_amount": format_money(amount),
    }
    item.update(extra or {})
    return item


def build_anomalies_by_type(anomalies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    labels = {
        "price_spike": "单价异常",
        "qty_spike": "采购量异常",
        "no_outbound": "长期不出库",
        "freq_change": "采购频率异常",
    }
    result = []
    for anomaly_type, label in labels.items():
        items = [item for item in anomalies if item["anomaly_type"] == anomaly_type]
        result.append({"type": anomaly_type, "type_label": label, "count": len(items), "items": items[:10]})
    return result


def traffic_for_total_value(trend: str) -> str:
    return {"快速上升": "red", "缓慢上升": "yellow"}.get(trend, "green")


def traffic_for_stagnant(ratio: float) -> str:
    if ratio < 0.05:
        return "green"
    if ratio <= 0.15:
        return "yellow"
    return "red"


def traffic_for_balance(ratio: float | None) -> str:
    if ratio is None:
        return "yellow"
    if 0.8 <= ratio <= 1.2:
        return "green"
    if ratio <= 1.5:
        return "yellow"
    return "red"


def traffic_for_anomalies(count: int, amount: float, transactions: list[Transaction]) -> str:
    inventory_value = sum(tx.amount if tx.trans_type == "入库" else -tx.amount for tx in transactions)
    if count == 0:
        return "green"
    if count > 5 or (inventory_value > 0 and amount > inventory_value * 0.1):
        return "red"
    return "yellow"


def overall_grade(indicators: list[dict[str, Any]]) -> str:
    lights = [item["traffic_light"] for item in indicators]
    if "red" in lights:
        return "red"
    if "yellow" in lights:
        return "yellow"
    return "green"


def score_for_grade(grade: str) -> int:
    return {"green": 92, "yellow": 68, "red": 38}[grade]


def overall_summary(indicators: list[dict[str, Any]]) -> str:
    red_count = sum(1 for item in indicators if item["traffic_light"] == "red")
    yellow_count = sum(1 for item in indicators if item["traffic_light"] == "yellow")
    if red_count >= 2:
        return "库存有点危险，建议马上开会处理"
    if red_count == 1 or yellow_count >= 2:
        return "库存持续增长需关注，建议尽快复盘采购节奏"
    if yellow_count == 1:
        return "库存整体还行，有一个指标需要盯住"
    return "库存管理良好，继续保持"


def action_suggestions(indicators: list[dict[str, Any]]) -> list[str]:
    suggestions = []
    by_id = {item["id"]: item for item in indicators}
    if by_id["stagnant_ratio"]["traffic_light"] != "green":
        suggestions.append("优先盘点处理呆滞物料，释放占用资金")
    if by_id["balance"]["traffic_light"] != "green":
        suggestions.append("控制采购节奏，让入库速度回到出库能力附近")
    if by_id["anomalies"]["traffic_light"] != "green":
        suggestions.append("让采购和仓库复核异常物料，确认是否为真实异常")
    return suggestions[:3] or ["继续保持当前库存节奏，每周复看一次"]


def summarize_total_value(total: float, trend: str) -> str:
    if trend in {"快速上升", "缓慢上升"}:
        return f"库存资金{format_money(total)}，近期{trend}，钱压在仓库里的趋势需要关注"
    if trend == "下降":
        return f"库存资金{format_money(total)}，近期在下降，资金压力有所缓解"
    return f"库存资金{format_money(total)}，整体趋势相对平稳"


def summarize_stagnant(ratio: float, amount: float, count: int) -> str:
    if ratio > 0.15:
        return f"呆滞物料占比{ratio:.1%}，{count}种物料占用{format_money(amount)}，需要优先处理"
    if ratio >= 0.05:
        return f"呆滞物料占比{ratio:.1%}，涉及{format_money(amount)}，超过常规水平"
    return f"呆滞物料占比{ratio:.1%}，处于健康范围"


def summarize_balance(ratio: float | None, judgment: str) -> str:
    if ratio is None:
        return "出库数据不足，暂时无法判断出入库平衡"
    if judgment == "平衡":
        return f"最近6个月出入比{ratio:.2f}，采购与消耗基本匹配"
    return f"最近6个月出入比{ratio:.2f}，{judgment}，库存容易继续累积"


def summarize_anomalies(count: int, amount: float) -> str:
    if count == 0:
        return "未检测到异常物料，一切正常"
    return f"发现{count}种物料异常，涉及{format_money(amount)}，建议人工复核"


def format_money(value: float) -> str:
    sign = "-" if value < 0 else ""
    abs_value = abs(value)
    if abs_value >= 100_000_000:
        return f"{sign}{abs_value / 100_000_000:.2f}亿"
    if abs_value >= 10_000:
        return f"{sign}{abs_value / 10_000:.1f}万"
    return f"{sign}{abs_value:.0f}元"
