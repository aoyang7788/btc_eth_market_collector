from __future__ import annotations

from pathlib import Path
from typing import Any


def _fmt(value: Any) -> str:
    if value is None:
        return "等待样本"
    return str(value)


def _fmt_pct(value: Any) -> str:
    if value is None:
        return "等待样本"
    return f"{value}%"


def write_performance_report(stats: dict[str, Any], path: Path) -> None:
    recent = stats.get("recent_10", {})
    recent_text = " ".join("止盈" if item == "TP" else "止损" if item == "SL" else item for item in recent.get("results", [])) or "暂无已完成交易"
    lines = [
        "# 信号统计日报",
        "",
        f"总交易：{stats.get('total_trades', 0)}",
        f"已完成：{stats.get('resolved_trades', 0)}",
        "",
        f"止盈次数：{stats.get('tp_count', 0)}",
        f"止损次数：{stats.get('sl_count', 0)}",
        f"胜率：{_fmt_pct(stats.get('win_rate'))}",
        f"平均盈亏比：{_fmt(stats.get('average_rr'))}",
        f"EV：{_fmt(stats.get('ev'))}",
        f"Profit Factor：{_fmt(stats.get('profit_factor'))}",
        f"最大连赢：{stats.get('max_win_streak', 0)}",
        f"最大连亏：{stats.get('max_loss_streak', 0)}",
        "",
        "最近10次：",
        recent_text,
        "",
        "## 统计说明",
        "",
        "- 只统计建议为“允许做多 / 允许做空”且具备 TP/SL 的信号。",
        "- TP/SL 通过后续 1小时、4小时、24小时快照价格观察触发。",
        "- 当前版本不接交易账户，不自动交易，只做记录与复盘。",
    ]
    path.write_text("\n".join(lines), encoding="utf-8-sig")
