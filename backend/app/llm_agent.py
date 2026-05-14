from __future__ import annotations

import copy
import json
import os
from typing import Any

from openai import OpenAI


DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_BASE_URL = "https://api.deepseek.com"

SYSTEM_PROMPT = """你是“库存健康度报告专家智能体”，服务对象是40-50岁制造业老板。

你的任务：
1. 基于后端已经计算好的结构化结果，生成老板3秒能看懂的结论。
2. 只解释库存资金、呆滞物料、出入库平衡、异常物料这4个指标。
3. 语言直接、克制、可执行，避免学术化和咨询腔。

硬性规则：
- 不重新计算任何数字。
- 不编造输入JSON中不存在的金额、比例、日期、物料名。
- 不把自动异常检测说成事实定罪，只能说“建议复核”。
- 输出必须是JSON对象，不要Markdown，不要代码块。
- overall_summary控制在28个汉字以内。
- action_suggestions输出1到3条，每条不超过28个汉字。
- indicator_summaries必须包含 total_value、stagnant_ratio、balance、anomalies 四个key。

输出JSON格式：
{
  "overall_summary": "一句话结论",
  "action_suggestions": ["建议1", "建议2"],
  "indicator_summaries": {
    "total_value": "库存资金摘要",
    "stagnant_ratio": "呆滞物料摘要",
    "balance": "出入库平衡摘要",
    "anomalies": "异常物料摘要"
  }
}
"""


def enhance_report_with_llm(overview: dict[str, Any], details: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    enhanced_overview = copy.deepcopy(overview)
    enhanced_details = copy.deepcopy(details)

    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    model = os.getenv("DEEPSEEK_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    base_url = os.getenv("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL

    if not api_key:
        metadata = _metadata(model=model, enabled=False, status="missing_api_key")
        _attach_metadata(enhanced_overview, enhanced_details, metadata)
        return enhanced_overview, enhanced_details

    try:
        result = _call_deepseek(api_key=api_key, model=model, base_url=base_url, overview=overview, details=details)
        _apply_llm_result(enhanced_overview, enhanced_details, result)
        metadata = _metadata(model=model, enabled=True, status="completed")
    except Exception as exc:
        metadata = _metadata(model=model, enabled=True, status="fallback", error=str(exc))

    _attach_metadata(enhanced_overview, enhanced_details, metadata)
    return enhanced_overview, enhanced_details


def _call_deepseek(
    *,
    api_key: str,
    model: str,
    base_url: str,
    overview: dict[str, Any],
    details: dict[str, Any],
) -> dict[str, Any]:
    client = OpenAI(api_key=api_key, base_url=base_url, timeout=30)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(_agent_input(overview, details), ensure_ascii=False)},
        ],
        temperature=0.2,
        max_tokens=1200,
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content or "{}"
    return json.loads(_strip_code_fence(content))


def _agent_input(overview: dict[str, Any], details: dict[str, Any]) -> dict[str, Any]:
    return {
        "prd_context": {
            "report_name": "库存健康度分析报告",
            "audience": "制造业老板",
            "principles": ["最小数据输入", "老板3秒看懂", "红黄绿灯", "异常检测需人工确认"],
            "indicators": ["库存总资金", "呆滞物料占比", "出入库平衡度", "异常物料检测"],
        },
        "computed_overview": {
            "overall_health": overview.get("overall_health"),
            "indicators": overview.get("indicators"),
            "data_quality": overview.get("data_quality"),
            "disclaimer": overview.get("disclaimer"),
        },
        "computed_details": {
            "total_value": _pick(
                details.get("total_value", {}),
                ["total_value", "display_value", "trend_direction", "traffic_light", "monthly"],
            ),
            "stagnant_ratio": _pick(
                details.get("stagnant_ratio", {}),
                ["ratio", "display_value", "display_amount", "count", "traffic_light", "top_list"],
            ),
            "balance": _pick(
                details.get("balance", {}),
                ["overall_ratio", "display_value", "judgment", "traffic_light", "monthly"],
            ),
            "anomalies": _pick(
                details.get("anomalies", {}),
                ["total", "display_amount", "breakdown", "traffic_light", "top_list"],
            ),
        },
    }


def _apply_llm_result(overview: dict[str, Any], details: dict[str, Any], result: dict[str, Any]) -> None:
    overall_summary = _clean_text(result.get("overall_summary"), max_len=60)
    if overall_summary:
        overview["overall_health"]["summary"] = overall_summary

    suggestions = [_clean_text(item, max_len=60) for item in result.get("action_suggestions", []) if _clean_text(item)]
    if suggestions:
        overview["overall_health"]["action_suggestions"] = suggestions[:3]

    indicator_summaries = result.get("indicator_summaries", {})
    if not isinstance(indicator_summaries, dict):
        return

    for indicator in overview.get("indicators", []):
        indicator_id = indicator.get("id")
        summary = _clean_text(indicator_summaries.get(indicator_id), max_len=120)
        if summary:
            indicator["summary"] = summary
            _update_detail_summary(details, indicator_id, summary)


def _update_detail_summary(details: dict[str, Any], indicator_id: str, summary: str) -> None:
    if indicator_id not in details:
        return
    if indicator_id == "total_value":
        details[indicator_id]["trend_analysis"] = summary
    elif indicator_id == "balance":
        details[indicator_id]["analysis"] = summary
    else:
        details[indicator_id]["summary"] = summary


def _metadata(*, model: str, enabled: bool, status: str, error: str | None = None) -> dict[str, Any]:
    metadata = {
        "type": "inventory_health_expert_agent",
        "provider": "deepseek",
        "model": model,
        "enabled": enabled,
        "status": status,
    }
    if error:
        metadata["error"] = error
    return metadata


def _attach_metadata(overview: dict[str, Any], details: dict[str, Any], metadata: dict[str, Any]) -> None:
    overview["llm_agent"] = metadata
    for detail in details.values():
        if isinstance(detail, dict):
            detail["llm_agent"] = metadata


def _strip_code_fence(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return text


def _clean_text(value: Any, max_len: int = 120) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().replace("\n", " ")[:max_len]


def _pick(value: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    return {key: value.get(key) for key in keys if key in value}
