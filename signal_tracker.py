from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any


RETURN_HORIZONS = {
    "after_1h_return_pct": 1,
    "after_4h_return_pct": 4,
    "after_24h_return_pct": 24,
}

RESULT_FIELDS = [
    "after_1h_result",
    "after_4h_result",
    "after_24h_result",
]

FIELDS = [
    "timestamp",
    "symbol",
    "price",
    "score",
    "risk_level",
    "action",
    "trend_15m",
    "trend_1h",
    "trend_4h",
    "funding_rate",
    "long_short_ratio",
    "oi",
    "ema5",
    "ema13",
    "ema50",
    "ema200",
    "macd_state",
    "bb_position",
    "after_1h_return_pct",
    "after_4h_return_pct",
    "after_24h_return_pct",
    "after_1h_result",
    "after_4h_result",
    "after_24h_result",
]


def parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _num(value: Any) -> float | None:
    try:
        if value in {"", None}:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt_num(value: Any) -> Any:
    number = _num(value)
    if number is None:
        return ""
    return round(number, 8)


def _round_pct(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 6)


def read_history(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = []
        for row in reader:
            rows.append({field: row.get(field, "") for field in FIELDS})
        return rows


def write_history(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in FIELDS})


def _price_map(snapshot: dict[str, Any]) -> dict[str, float]:
    result = {}
    for symbol, data in snapshot.get("symbols", {}).items():
        price = _num(data.get("price", {}).get("last"))
        if price is not None:
            result[symbol] = price
    return result


def _action(decision_item: dict[str, Any]) -> str:
    if decision_item.get("allow_long"):
        return "ALLOW_LONG"
    if decision_item.get("allow_short"):
        return "ALLOW_SHORT"
    return "WAIT"


def _macd_state(macd: dict[str, Any]) -> str:
    hist = _num(macd.get("histogram"))
    if hist is None:
        return "missing"
    if hist > 0:
        return "bullish"
    if hist < 0:
        return "bearish"
    return "neutral"


def _bb_position(price: Any, bollinger: dict[str, Any]) -> str:
    value = _num(price)
    upper = _num(bollinger.get("upper"))
    middle = _num(bollinger.get("middle"))
    lower = _num(bollinger.get("lower"))
    if value is None or upper is None or middle is None or lower is None:
        return "missing"
    if value > upper:
        return "above_upper"
    if value < lower:
        return "below_lower"
    if value >= middle:
        return "upper_half"
    return "lower_half"


def _score(snapshot_item: dict[str, Any], decision_item: dict[str, Any]) -> int:
    score = 50
    action = _action(decision_item)
    consistency = decision_item.get("three_period_consistency")
    risk = decision_item.get("risk_level")
    structures = decision_item.get("structures", {})
    tf4h = snapshot_item.get("timeframes", {}).get("4h", {})
    price = _num(snapshot_item.get("price", {}).get("last"))
    ema50 = _num(tf4h.get("ema50"))
    ema200 = _num(tf4h.get("ema200"))
    macd_hist = _num(tf4h.get("macd", {}).get("histogram"))

    if action in {"ALLOW_LONG", "ALLOW_SHORT"}:
        score += 20
    else:
        score -= 5
    if consistency in {"bullish_aligned", "bearish_aligned"}:
        score += 15
    elif consistency in {"bullish_pullback", "bearish_pullback"}:
        score += 10
    elif consistency == "conflict":
        score -= 25

    if structures.get("4h") == structures.get("1h") and structures.get("4h") in {"bullish", "bearish"}:
        score += 10
    if structures.get("15m") == structures.get("4h") and structures.get("15m") in {"bullish", "bearish"}:
        score += 5

    if macd_hist is None:
        score -= 5
    elif (action == "ALLOW_LONG" and macd_hist > 0) or (action == "ALLOW_SHORT" and macd_hist < 0):
        score += 5

    if price is None or ema50 is None or ema200 is None:
        score -= 5
    elif action == "ALLOW_LONG" and price >= ema50 >= ema200:
        score += 5
    elif action == "ALLOW_SHORT" and price <= ema50 <= ema200:
        score += 5

    if risk == "LOW":
        score += 10
    elif risk == "HIGH":
        score -= 20
    return max(0, min(100, score))


def _build_rows(snapshot: dict[str, Any], decision: dict[str, Any]) -> list[dict[str, Any]]:
    timestamp = decision.get("generated_at", "")
    rows = []
    for symbol, decision_item in decision.get("symbols", {}).items():
        snapshot_item = snapshot.get("symbols", {}).get(symbol, {})
        tf4h = snapshot_item.get("timeframes", {}).get("4h", {})
        derivatives = snapshot_item.get("derivatives", {})
        structures = decision_item.get("structures", {})
        price = snapshot_item.get("price", {}).get("last")
        rows.append(
            {
                "timestamp": timestamp,
                "symbol": symbol,
                "price": _fmt_num(price),
                "score": _score(snapshot_item, decision_item),
                "risk_level": decision_item.get("risk_level", ""),
                "action": _action(decision_item),
                "trend_15m": structures.get("15m", ""),
                "trend_1h": structures.get("1h", ""),
                "trend_4h": structures.get("4h", ""),
                "funding_rate": _fmt_num(derivatives.get("funding_rate")),
                "long_short_ratio": _fmt_num(derivatives.get("long_short_ratio")),
                "oi": _fmt_num(derivatives.get("open_interest")),
                "ema5": _fmt_num(tf4h.get("ema5")),
                "ema13": _fmt_num(tf4h.get("ema13")),
                "ema50": _fmt_num(tf4h.get("ema50")),
                "ema200": _fmt_num(tf4h.get("ema200")),
                "macd_state": _macd_state(tf4h.get("macd", {})),
                "bb_position": _bb_position(price, tf4h.get("bollinger", {})),
                "after_1h_return_pct": "",
                "after_4h_return_pct": "",
                "after_24h_return_pct": "",
                "after_1h_result": "",
                "after_4h_result": "",
                "after_24h_result": "",
            }
        )
    return rows


def _judge_result(action: str, return_pct: float | None) -> str:
    if return_pct is None:
        return ""
    if action == "ALLOW_LONG":
        return "correct" if return_pct > 0 else "wrong"
    if action == "ALLOW_SHORT":
        return "correct" if return_pct < 0 else "wrong"
    if action == "WAIT":
        if abs(return_pct) < 1:
            return "correct_wait"
        if return_pct > 3 or return_pct < -3:
            return "missed_opportunity"
        return "neutral_wait"
    return ""


def update_signal_history(snapshot: dict[str, Any], decision: dict[str, Any], history_path: Path) -> list[dict[str, Any]]:
    rows = read_history(history_path)
    prices = _price_map(snapshot)
    current_time = parse_iso(snapshot.get("generated_at", "")) or now_utc()

    for row in rows:
        timestamp = parse_iso(row.get("timestamp", ""))
        symbol = row.get("symbol", "")
        entry_price = _num(row.get("price"))
        if not timestamp or symbol not in prices or entry_price is None or entry_price <= 0:
            continue

        elapsed_hours = (current_time - timestamp.astimezone(timezone.utc)).total_seconds() / 3600
        raw_return = _round_pct((prices[symbol] - entry_price) / entry_price * 100)
        action = row.get("action", "")
        for field, hours in RETURN_HORIZONS.items():
            result_field = field.replace("_return_pct", "_result")
            existing_return = _num(row.get(field))
            if existing_return is not None and row.get(result_field) in {"", None}:
                row[result_field] = _judge_result(action, existing_return)
            elif row.get(field) in {"", None} and elapsed_hours >= hours:
                row[field] = raw_return
                row[result_field] = _judge_result(action, raw_return)

    existing_keys = {(row.get("timestamp"), row.get("symbol")) for row in rows}
    for new_row in _build_rows(snapshot, decision):
        key = (new_row.get("timestamp"), new_row.get("symbol"))
        if key not in existing_keys:
            rows.append(new_row)
            existing_keys.add(key)

    write_history(history_path, rows)
    return rows


def _resolved_result(row: dict[str, Any]) -> str:
    for field in ["after_24h_result", "after_4h_result", "after_1h_result"]:
        result = row.get(field, "")
        if result:
            return result
    return ""


def _action_stats(rows: list[dict[str, Any]], action: str) -> dict[str, Any]:
    action_rows = [row for row in rows if row.get("action") == action]
    results = [_resolved_result(row) for row in action_rows]
    resolved = [result for result in results if result]
    if action == "WAIT":
        correct = [result for result in resolved if result == "correct_wait"]
        return {
            "count": len(action_rows),
            "correct": len(correct),
            "wrong": len([result for result in resolved if result == "missed_opportunity"]),
            "resolved": len(resolved),
            "accuracy": round(len(correct) / len(resolved) * 100, 2) if resolved else None,
        }

    correct = [result for result in resolved if result == "correct"]
    return {
        "count": len(action_rows),
        "correct": len(correct),
        "wrong": len([result for result in resolved if result == "wrong"]),
        "resolved": len(resolved),
        "win_rate": round(len(correct) / len(resolved) * 100, 2) if resolved else None,
    }


def _recent_10(rows: list[dict[str, Any]]) -> dict[str, Any]:
    resolved_rows = [row for row in rows if _resolved_result(row)]
    recent = resolved_rows[-10:]
    wins = 0
    losses = 0
    for row in recent:
        result = _resolved_result(row)
        if result in {"correct", "correct_wait"}:
            wins += 1
        elif result in {"wrong", "missed_opportunity"}:
            losses += 1
    total = wins + losses
    return {
        "count": len(recent),
        "wins": wins,
        "losses": losses,
        "accuracy": round(wins / total * 100, 2) if total else None,
    }


def build_signal_statistics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    allow_long = _action_stats(rows, "ALLOW_LONG")
    allow_short = _action_stats(rows, "ALLOW_SHORT")
    wait = _action_stats(rows, "WAIT")
    correct = int(allow_long["correct"]) + int(allow_short["correct"]) + int(wait["correct"])
    wrong = int(allow_long["wrong"]) + int(allow_short["wrong"]) + int(wait["wrong"])
    total_resolved = correct + wrong
    return {
        "total_signals": len(rows),
        "resolved_signals": total_resolved,
        "correct": correct,
        "wrong": wrong,
        "overall_accuracy": round(correct / total_resolved * 100, 2) if total_resolved else None,
        "allow_long": allow_long,
        "allow_short": allow_short,
        "wait": wait,
        "recent_10": _recent_10(rows),
    }


def write_statistics_json(stats: dict[str, Any], path: Path) -> None:
    path.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
