from __future__ import annotations

from pathlib import Path
from typing import Any


def _fmt_pct(value: Any) -> str:
    if value is None:
        return "pending"
    return f"{value}%"


def write_performance_report(stats: dict[str, Any], path: Path) -> None:
    allow_long = stats.get("allow_long", {})
    allow_short = stats.get("allow_short", {})
    wait = stats.get("wait", {})
    recent = stats.get("recent_10", {})

    lines = [
        "# 信号统计日报",
        "",
        f"总信号：{stats.get('total_signals', 0)}",
        "",
        f"已评估：{stats.get('resolved_signals', 0)}",
        f"正确：{stats.get('correct', 0)}",
        f"错误：{stats.get('wrong', 0)}",
        f"总体准确率：{_fmt_pct(stats.get('overall_accuracy'))}",
        "",
        f"ALLOW_LONG：{_fmt_pct(allow_long.get('win_rate'))}",
        f"- 次数：{allow_long.get('count', 0)}",
        f"- 已评估：{allow_long.get('resolved', 0)}",
        f"- 正确：{allow_long.get('correct', 0)}",
        f"- 错误：{allow_long.get('wrong', 0)}",
        "",
        f"ALLOW_SHORT：{_fmt_pct(allow_short.get('win_rate'))}",
        f"- 次数：{allow_short.get('count', 0)}",
        f"- 已评估：{allow_short.get('resolved', 0)}",
        f"- 正确：{allow_short.get('correct', 0)}",
        f"- 错误：{allow_short.get('wrong', 0)}",
        "",
        f"WAIT：{_fmt_pct(wait.get('accuracy'))}",
        f"- 次数：{wait.get('count', 0)}",
        f"- 已评估：{wait.get('resolved', 0)}",
        f"- 正确等待：{wait.get('correct', 0)}",
        f"- 错失机会：{wait.get('wrong', 0)}",
        "",
        f"最近10次：{_fmt_pct(recent.get('accuracy'))}",
        f"- {recent.get('wins', 0)}胜{recent.get('losses', 0)}负",
        "",
        "## 判定规则",
        "",
        "- ALLOW_LONG：记录后价格上涨为正确，下跌为错误。",
        "- ALLOW_SHORT：记录后价格下跌为正确，上涨为错误。",
        "- WAIT：价格波动小于 ±1% 为正确等待；上涨超过3%或下跌超过3%为错失机会；其余为中性等待。",
        "- 统计以已到期的 1h / 4h / 24h 结果为准，优先使用 24h，其次 4h，再其次 1h。",
    ]

    path.write_text("\n".join(lines), encoding="utf-8-sig")
