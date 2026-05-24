from __future__ import annotations

from pathlib import Path
from typing import Any


def _fmt(value: Any) -> str:
    if value is None:
        return "pending"
    return str(value)


def _escape_table(value: Any) -> str:
    return _fmt(value).replace("|", "\\|")


def write_performance_report(stats: dict[str, Any], path: Path) -> None:
    actions = stats.get("actions", {})
    long_stats = actions.get("LOOK_FOR_LONG", {})
    short_stats = actions.get("LOOK_FOR_SHORT", {})
    wait_stats = actions.get("WAIT", {})
    no_trade_stats = actions.get("NO_TRADE", {})

    lines = [
        "# BTC/ETH 三周期信号追踪与复盘报告",
        "",
        "说明：本报告只统计历史决策信号与后续市场表现，不预测未来，不连接交易账户，不自动交易。",
        "",
        f"累计信号数：{stats.get('total_signals')}",
        f"样本提示：{stats.get('sample_size_note')}",
        "",
        "## LOOK_FOR_LONG",
        "",
        f"- 次数：{_fmt(long_stats.get('count'))}",
        f"- 已完成复盘次数：{_fmt(long_stats.get('resolved_count'))}",
        f"- 胜率：{_fmt(long_stats.get('win_rate'))}%",
        f"- 平均涨幅：{_fmt(long_stats.get('average_favorable_return_pct'))}%",
        f"- 最大涨幅：{_fmt(long_stats.get('max_favorable_return_pct'))}%",
        f"- 最大回撤：{_fmt(long_stats.get('max_adverse_move_pct'))}%",
        "",
        "## LOOK_FOR_SHORT",
        "",
        f"- 次数：{_fmt(short_stats.get('count'))}",
        f"- 已完成复盘次数：{_fmt(short_stats.get('resolved_count'))}",
        f"- 胜率：{_fmt(short_stats.get('win_rate'))}%",
        f"- 平均跌幅：{_fmt(short_stats.get('average_favorable_return_pct'))}%",
        f"- 最大跌幅：{_fmt(short_stats.get('max_favorable_return_pct'))}%",
        f"- 最大反向波动：{_fmt(short_stats.get('max_adverse_move_pct'))}%",
        "",
        "## WAIT",
        "",
        f"- 次数：{_fmt(wait_stats.get('count'))}",
        "",
        "## NO_TRADE",
        "",
        f"- 次数：{_fmt(no_trade_stats.get('count'))}",
        "",
        "## 周期组合统计",
        "",
    ]

    combo_stats = stats.get("cycle_combo_stats", [])
    if combo_stats:
        lines.append("| 周期组合 | 次数 | 已复盘 | 胜率 | 平均有利波动 |")
        lines.append("| --- | ---: | ---: | ---: | ---: |")
        for item in combo_stats[:20]:
            lines.append(
                f"| {_escape_table(item.get('combo'))} | {item.get('count')} | {item.get('resolved_count')} | "
                f"{_fmt(item.get('win_rate'))}% | {_fmt(item.get('average_favorable_return_pct'))}% |"
            )
    else:
        lines.append("暂无周期组合数据。")

    lines.extend(
        [
            "",
            "## 自动评估状态",
            "",
        ]
    )
    if int(stats.get("total_signals") or 0) < 100:
        lines.extend(
            [
                "- 哪种信号最有效：样本不足，暂不判断。",
                "- 哪个周期组合胜率最高：样本不足，暂不判断。",
                "- 是否存在稳定优势：样本不足，暂不判断。",
            ]
        )
    else:
        ranked = [
            item
            for item in combo_stats
            if item.get("resolved_count") and item.get("average_favorable_return_pct") is not None
        ]
        best_combo = ranked[0] if ranked else None
        lines.extend(
            [
                f"- 哪种信号最有效：参考 LOOK_FOR_LONG / LOOK_FOR_SHORT 中胜率和平均有利波动更高者。",
                f"- 当前样本内最佳周期组合：{_escape_table(best_combo.get('combo')) if best_combo else 'pending'}",
                "- 是否存在稳定优势：需要结合样本外和前向观察继续确认。",
            ]
        )

    lines.extend(
        [
            "",
            "## 复盘原则",
            "",
            "- 未到期的 1h / 4h / 24h / 72h / 7d 收益保持空值。",
            "- 到期后首次运行系统时，用当次 market_snapshot.json 的价格回填对应周期收益。",
            "- 信号累计不足100次前，只做观察，不判断稳定优势。",
        ]
    )

    path.write_text("\n".join(lines), encoding="utf-8-sig")
