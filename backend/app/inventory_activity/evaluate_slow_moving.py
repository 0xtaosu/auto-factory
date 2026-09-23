from __future__ import annotations

from .common import ActivityError, digest, iso_date


def validate_policy(policy: dict) -> dict:
    required = {"policy_id", "policy_name", "metric", "operator", "threshold_value", "threshold_unit",
                "effective_from", "effective_to", "material_category"}
    if required - policy.keys():
        raise ActivityError("策略字段不完整: " + ", ".join(sorted(required - policy.keys())))
    if policy["metric"] != "DaysSinceLastMovement" or policy["operator"] != ">=" or policy["threshold_unit"] != "day":
        raise ActivityError("MVP 仅支持 DaysSinceLastMovement >= 阈值天数")
    if type(policy["threshold_value"]) is not int or policy["threshold_value"] < 0:
        raise ActivityError("策略阈值必须为非负整数")
    for key in ("policy_id", "policy_name", "material_category"):
        if not isinstance(policy[key], str) or not policy[key].strip():
            raise ActivityError(f"策略 {key} 不能为空")
    start = iso_date(policy["effective_from"], "策略生效日")
    if policy["effective_to"] is not None and iso_date(policy["effective_to"], "策略失效日") < start:
        raise ActivityError("策略有效期倒置")
    return {**policy, "policy_snapshot_id": "policy/" + digest(policy)}


def evaluate_slow_moving(materials: list[dict], summaries: dict, run: dict, policy: dict) -> list[dict]:
    assessments = []
    for material in materials:
        code = material["material_code"]
        metrics = summaries[code]
        applicable = (policy["effective_from"] <= run["observation_date"] and
                      (policy["effective_to"] is None or run["observation_date"] <= policy["effective_to"]) and
                      policy["material_category"] in {"*", material["material_category"]})
        days = metrics["days_since_last_movement"]
        candidate = days >= policy["threshold_value"] if applicable and days is not None else None
        classification = "InactiveMaterialCandidate" if candidate else "ActiveMaterial" if candidate is False else "NotEvaluated"
        assessments.append({
            **{k: material[k] for k in ("material_code", "material_name", "material_specification", "material_category", "unit")},
            **metrics, "assessment_id": f"assessment/{run['run_id']}/{code}",
            "observation_date": run["observation_date"], "data_window_start": run["data_window_start"],
            "data_window_end": run["data_window_end"], "policy_id": policy["policy_id"],
            "policy_snapshot_id": policy["policy_snapshot_id"], "threshold_value": policy["threshold_value"],
            "inactive_candidate": candidate, "classification": classification,
            "evaluation_status": "evaluated" if candidate is not None else "no_observed_movement" if days is None else "policy_not_applicable",
            "left_censored_population": True,
            "metadata_conflicts": material["metadata_conflicts"],
        })
    return sorted(assessments, key=lambda a: (-(a["days_since_last_movement"] if a["days_since_last_movement"] is not None else -1), a["material_code"]))
