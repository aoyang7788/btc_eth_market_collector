from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any


FIELDS = [
    "timestamp",
    "symbol",
    "entry_price",
    "action",
    "score",
    "risk_level",
    "ema5",
    "ema13",
    "ema50",
    "ema200",
    "macd",
    "bollinger",
    "funding_rate",
    "long_short_ratio",
    "oi",
    "stop_loss",
    "take_profit",
    "risk_reward",
    "result",
    "result_at",
    "result_horizon",
]

HORIZONS = {
    "1h": 1,
    "4h": 4,
    "24h": 24,
}


def parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _num(value: Any) -> float | None:
    try:
        if value in {"", None}:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _round(value: Any, digits: int = 8) -> Any:
    number = _num(value)
    if number is None:
        return ""
    return round(number, digits)


def _action(decision_item: dict[str, Any]) -> str:
    if decision_item.get("allow_long"):
        return "允许做多"
    if decision_item.get("allow_short"):
        return "允许做空"
    return "观望等待"


def _risk(value: Any) -> str:
    return {
        "LOW": "低风险",
        "MEDIUM": "中风险",
        "HIGH": "高风险",
    }.get(str(value), str(value or ""))


def _macd_state(macd: dict[str, Any]) -> str:
    macd_line = _num(macd.get("macd"))
    signal = _num(macd.get("signal"))
    hist = _num(macd.get("histogram"))
    if macd_line is None or signal is None:
        return "缺失"
    if macd_line > signal and (hist or 0) >= 0:
        return "金叉"
    if macd_line < signal and (hist or 0) <= 0:
        return "死叉"
    return "中性"


def _bb_position(price: Any, bollinger: dict[str, Any]) -> str:
    value = _num(price)
    upper = _num(bollinger.get("upper"))
    middle = _num(bollinger.get("middle"))
    lower = _num(bollinger.get("lower"))
    if value is None or upper is None or middle is None or lower is None:
        return "缺失"
    if value > upper:
        return "上轨上方"
    if value < lower:
        return "下轨下方"
    if value >= middle:
        return "中轨上方"
    return "中轨下方"


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

    if action in {"允许做多", "允许做空"}:
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
    elif (action == "允许做多" and macd_hist > 0) or (action == "允许做空" and macd_hist < 0):
        score += 5

    if price is None or ema50 is None or ema200 is None:
        score -= 5
    elif action == "允许做多" and price >= ema50 >= ema200:
        score += 5
    elif action == "允许做空" and price <= ema50 <= ema200:
        score += 5

    if risk == "LOW":
        score += 10
    elif risk == "HIGH":
        score -= 20
    return max(0, min(100, score))


def _trade_plan(action: str, entry: float | None, tf15: dict[str, Any]) -> dict[str, Any]:
    if entry is None or action not in {"允许做多", "允许做空"}:
        return {"stop_loss": "", "take_profit": "", "risk_reward": ""}

    atr = _num(tf15.get("atr14"))
    range_data = tf15.get("recent_range", {})
    recent_low = _num(range_data.get("low"))
    recent_high = _num(range_data.get("high"))
    atr_distance = atr * 1.5 if atr is not None else None

    if action == "允许做多":
        candidates = []
        if recent_low is not None and recent_low < entry:
            candidates.append(recent_low)
        if atr_distance is not None:
            candidates.append(entry - atr_distance)
        if not candidates:
            return {"stop_loss": "", "take_profit": "", "risk_reward": ""}
        stop = max(candidates)
        risk = entry - stop
        take_profit = entry + risk * 2.5
    else:
        candidates = []
        if recent_high is not None and recent_high > entry:
            candidates.append(recent_high)
        if atr_distance is not None:
            candidates.append(entry + atr_distance)
        if not candidates:
            return {"stop_loss": "", "take_profit": "", "risk_reward": ""}
        stop = min(candidates)
        risk = stop - entry
        take_profit = entry - risk * 2.5

    if risk <= 0:
        return {"stop_loss": "", "take_profit": "", "risk_reward": ""}
    return {
        "stop_loss": round(stop, 8),
        "take_profit": round(take_profit, 8),
        "risk_reward": 2.5,
    }


def read_history(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return [{field: row.get(field, "") for field in FIELDS} for row in reader]


def write_history(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in FIELDS})


def _build_rows(snapshot: dict[str, Any], decision: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    timestamp = decision.get("generated_at", "")
    for symbol, decision_item in decision.get("symbols", {}).items():
        snapshot_item = snapshot.get("symbols", {}).get(symbol, {})
        tf15 = snapshot_item.get("timeframes", {}).get("15m", {})
        tf4h = snapshot_item.get("timeframes", {}).get("4h", {})
        derivatives = snapshot_item.get("derivatives", {})
        entry = _num(snapshot_item.get("price", {}).get("last"))
        action = _action(decision_item)
        plan = _trade_plan(action, entry, tf15)
        rows.append(
            {
                "timestamp": timestamp,
                "symbol": symbol,
                "entry_price": _round(entry),
                "action": action,
                "score": _score(snapshot_item, decision_item),
                "risk_level": _risk(decision_item.get("risk_level")),
                "ema5": _round(tf4h.get("ema5")),
                "ema13": _round(tf4h.get("ema13")),
                "ema50": _round(tf4h.get("ema50")),
                "ema200": _round(tf4h.get("ema200")),
                "macd": _macd_state(tf4h.get("macd", {})),
                "bollinger": _bb_position(entry, tf4h.get("bollinger", {})),
                "funding_rate": _round(derivatives.get("funding_rate")),
                "long_short_ratio": _round(derivatives.get("long_short_ratio")),
                "oi": _round(derivatives.get("open_interest")),
                "stop_loss": plan["stop_loss"],
                "take_profit": plan["take_profit"],
                "risk_reward": plan["risk_reward"],
                "result": "",
                "result_at": "",
                "result_horizon": "",
            }
        )
    return rows


def _price_map(snapshot: dict[str, Any]) -> dict[str, float]:
    result = {}
    for symbol, data in snapshot.get("symbols", {}).items():
        price = _num(data.get("price", {}).get("last"))
        if price is not None:
            result[symbol] = price
    return result


def _check_result(row: dict[str, Any], price: float) -> str:
    action = row.get("action", "")
    stop = _num(row.get("stop_loss"))
    take = _num(row.get("take_profit"))
    if stop is None or take is None:
        return ""
    if action == "允许做多":
        if price >= take:
            return "TP"
        if price <= stop:
            return "SL"
    if action == "允许做空":
        if price <= take:
            return "TP"
        if price >= stop:
            return "SL"
    return ""


def update_signal_history(snapshot: dict[str, Any], decision: dict[str, Any], history_path: Path) -> list[dict[str, Any]]:
    rows = read_history(history_path)
    prices = _price_map(snapshot)
    current_time = parse_iso(snapshot.get("generated_at", "")) or datetime.now(timezone.utc)

    for row in rows:
        if row.get("result"):
            continue
        timestamp = parse_iso(row.get("timestamp", ""))
        symbol = row.get("symbol", "")
        if not timestamp or symbol not in prices:
            continue
        elapsed_hours = (current_time - timestamp.astimezone(timezone.utc)).total_seconds() / 3600
        reached = [horizon for horizon, hours in HORIZONS.items() if elapsed_hours >= hours]
        if reached:
            result = _check_result(row, prices[symbol])
            if result:
                row["result"] = result
                row["result_at"] = snapshot.get("generated_at", "")
                row["result_horizon"] = reached[-1]

    existing_keys = {(row.get("timestamp"), row.get("symbol")) for row in rows}
    for new_row in _build_rows(snapshot, decision):
        key = (new_row.get("timestamp"), new_row.get("symbol"))
        if key not in existing_keys:
            rows.append(new_row)
            existing_keys.add(key)

    write_history(history_path, rows)
    return rows


def _trade_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if row.get("action") in {"允许做多", "允许做空"} and _num(row.get("risk_reward")) is not None]


def _max_streak(results: list[str], target: str) -> int:
    best = 0
    current = 0
    for result in results:
        if result == target:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def build_signal_statistics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    trades = _trade_rows(rows)
    resolved = [row for row in trades if row.get("result") in {"TP", "SL"}]
    tp_count = len([row for row in resolved if row.get("result") == "TP"])
    sl_count = len([row for row in resolved if row.get("result") == "SL"])
    rr_values = [_num(row.get("risk_reward")) for row in trades if _num(row.get("risk_reward")) is not None]
    avg_rr = round(mean(rr_values), 4) if rr_values else None
    losses = sl_count
    profit_factor = round(sum(_num(row.get("risk_reward")) or 0 for row in resolved if row.get("result") == "TP") / losses, 4) if losses else None
    ev = None
    if resolved:
        win_rate_raw = tp_count / len(resolved)
        avg_win = mean([_num(row.get("risk_reward")) or 0 for row in resolved if row.get("result") == "TP"]) if tp_count else 0
        ev = round(win_rate_raw * avg_win - (1 - win_rate_raw) * 1, 4)
    result_sequence = [row.get("result", "") for row in resolved]
    recent = result_sequence[-10:]
    return {
        "total_signals": len(rows),
        "total_trades": len(trades),
        "resolved_trades": len(resolved),
        "tp_count": tp_count,
        "sl_count": sl_count,
        "win_rate": round(tp_count / len(resolved) * 100, 2) if resolved else None,
        "average_rr": avg_rr,
        "ev": ev,
        "profit_factor": profit_factor,
        "max_win_streak": _max_streak(result_sequence, "TP"),
        "max_loss_streak": _max_streak(result_sequence, "SL"),
        "recent_10": {
            "results": recent,
            "tp": len([r for r in recent if r == "TP"]),
            "sl": len([r for r in recent if r == "SL"]),
        },
    }


def write_statistics_json(stats: dict[str, Any], path: Path) -> None:
    path.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
