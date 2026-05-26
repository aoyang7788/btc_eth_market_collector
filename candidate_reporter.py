from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import output_dir
from telegram_notifier import send_telegram_message


OBSERVER_FILE = "candidate_observer.csv"


def _num(value: Any) -> float | None:
    try:
        if value in {"", None}:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _status_counts(rows: list[dict[str, str]]) -> dict[str, int]:
    statuses = ["waiting", "filled", "expired", "tp", "sl"]
    return {status: len([row for row in rows if row.get("status") == status]) for status in statuses}


def _result_counts(rows: list[dict[str, str]]) -> dict[str, int]:
    return {
        "tp": len([row for row in rows if row.get("result") == "tp" or row.get("status") == "tp"]),
        "sl": len([row for row in rows if row.get("result") == "sl" or row.get("status") == "sl"]),
    }


def _fmt(value: Any) -> str:
    number = _num(value)
    if number is None:
        return str(value or "暂无")
    return f"{number:.4f}".rstrip("0").rstrip(".")


def _status_cn(value: str) -> str:
    return {
        "waiting": "等待回踩",
        "filled": "已触发入场",
        "expired": "已过期",
        "tp": "已止盈",
        "sl": "已止损",
    }.get(value, value or "未知")


def _direction_cn(value: str) -> str:
    return {"long": "做多", "short": "做空"}.get(value, value or "未知")


def build_candidate_report(rows: list[dict[str, str]]) -> str:
    counts = _status_counts(rows)
    results = _result_counts(rows)
    resolved = results["tp"] + results["sl"]
    win_rate = results["tp"] / resolved * 100 if resolved else None
    r_values = [_num(row.get("r_result")) for row in rows if _num(row.get("r_result")) is not None]
    cumulative_r = sum(r_values)

    lines = [
        "【候选策略观察日报】",
        "",
        f"生成时间：{datetime.now(timezone.utc).isoformat()}",
        "",
        "统计摘要：",
        f"总候选信号数：{len(rows)}",
        f"waiting：{counts['waiting']}",
        f"filled：{counts['filled']}",
        f"expired：{counts['expired']}",
        f"TP：{results['tp']}",
        f"SL：{results['sl']}",
        f"当前胜率：{f'{win_rate:.2f}%' if win_rate is not None else '暂无已完成样本'}",
        f"累计R：{cumulative_r:.4f}".rstrip("0").rstrip("."),
        "",
        "最近10条记录：",
    ]

    recent = rows[-10:]
    if not recent:
        lines.append("暂无候选记录。")
    for row in recent:
        lines.extend(
            [
                "",
                f"- 时间：{row.get('timestamp', '')}",
                f"  方向：{_direction_cn(row.get('direction', ''))}",
                f"  状态：{_status_cn(row.get('status', ''))}",
                f"  信号价：{_fmt(row.get('signal_price'))}",
                f"  实体中位：{_fmt(row.get('body_mid_entry'))}",
                f"  结果：{row.get('result') or '观察中'}",
                f"  R：{_fmt(row.get('r_result'))}",
            ]
        )
    return "\n".join(lines)


def run_report() -> dict[str, Any]:
    path = output_dir() / OBSERVER_FILE
    rows = _read_rows(path)
    text = build_candidate_report(rows)
    result = send_telegram_message(text)
    return {"path": str(path), "rows": len(rows), "text": text, "telegram": result}


def main() -> None:
    result = run_report()
    print(f"source: {result['path']}")
    print(f"rows: {result['rows']}")
    print("telegram:", "ok" if result["telegram"].get("ok") else result["telegram"].get("error"))
    print("--- preview ---")
    print(result["text"])


if __name__ == "__main__":
    main()
