from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_decision_json(decision: dict[str, Any], path: Path) -> None:
    path.write_text(json.dumps(decision, ensure_ascii=False, indent=2), encoding="utf-8")


def write_decision_markdown(decision: dict[str, Any], path: Path) -> None:
    lines = [
        "# BTC/ETH 三周期市场决策报告",
        "",
        f"生成时间：{decision.get('generated_at')}",
        "",
        "说明：本报告只做市场状态判断，不预测价格，不给涨跌目标，不连接交易所，不下单。",
        "",
        f"允许动作：{', '.join(decision.get('allowed_actions', []))}",
        "",
    ]

    for symbol, data in decision.get("symbols", {}).items():
        structures = data.get("structures", {})
        lines.extend(
            [
                f"## {symbol}",
                "",
                f"- 当前价格：{data.get('price')}",
                f"- 15m结构判断：{structures.get('15m')}",
                f"- 1h结构判断：{structures.get('1h')}",
                f"- 4h结构判断：{structures.get('4h')}",
                f"- 三周期一致性判断：{data.get('three_period_consistency')}",
                f"- 风险等级：{data.get('risk_level')}",
                "",
                "### 原因",
                "",
            ]
        )
        if data.get("observation_only"):
            lines.insert(-3, "- ETH 当前仅观察，不参与交易统计。")
        else:
            insert_at = len(lines) - 3
            lines[insert_at:insert_at] = [
                f"- 是否允许做多：{str(data.get('allow_long')).lower()}",
                f"- 是否允许做空：{str(data.get('allow_short')).lower()}",
                f"- 是否允许交易：{str(data.get('allow_trade')).lower()}",
                f"- 建议动作：{data.get('suggested_action')}",
            ]
        reasons = data.get("reason", [])
        if reasons:
            lines.extend([f"- {item}" for item in reasons])
        else:
            lines.append("- none")

        warnings = data.get("warnings", [])
        lines.extend(["", "### 风险提示", ""])
        if warnings:
            lines.extend([f"- {item}" for item in warnings])
        else:
            lines.append("- none")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8-sig")
