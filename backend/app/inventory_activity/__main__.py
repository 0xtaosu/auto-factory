from __future__ import annotations

import argparse
from pathlib import Path

from .common import ActivityError, defaults, dumps, read_config
from .export_results import export_results
from .pipeline import analyze_workbook, explain


def main() -> None:
    parser = argparse.ArgumentParser(description="ERP 物料活跃度：事件 → 指标 → 策略 → 可追溯候选")
    parser.add_argument("excel", type=Path)
    parser.add_argument("--output", type=Path, default=Path("data/processed"))
    parser.add_argument("--report", type=Path, default=Path("reports/inventory-activity-mvp.md"))
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--settings", type=Path)
    parser.add_argument("--observation-date")
    parser.add_argument("--threshold-days", type=int)
    parser.add_argument("--explain", metavar="MATERIAL_CODE")
    args = parser.parse_args()
    config = defaults()
    settings = read_config(args.settings) if args.settings else {}
    policy = read_config(args.policy) if args.policy else config["policy"]
    if args.observation_date:
        settings["observation_date"] = args.observation_date
        settings["frequency_window_end"] = min(settings.get("frequency_window_end", config["frequency_window_end"]), args.observation_date)
    if args.threshold_days is not None:
        policy["threshold_value"] = args.threshold_days
        policy["policy_id"] = f"slow-moving-custom-{args.threshold_days}d"
    try:
        content = args.excel.read_bytes()
        result = analyze_workbook(content, args.excel.name, settings, policy)
        export_results(result, args.output, args.report)
        (args.output / "source.xlsx").write_bytes(content)
        print(dumps(result["overview"], indent=2))
        if args.explain:
            print(dumps(explain(result, args.explain), indent=2))
    except (ActivityError, KeyError, OSError) as exc:
        parser.exit(1, f"分析失败: {exc}\n")


if __name__ == "__main__":
    main()
