from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from collectors.binance_futures import BinanceFuturesClient
from config import output_dir
from indicators.technicals import parse_klines


FIELDS = [
    "timestamp",
    "symbol",
    "direction",
    "signal_price",
    "body_mid_entry",
    "wait_window_bars",
    "stop_loss",
    "take_profit",
    "risk_reward",
    "status",
    "filled_price",
    "result",
    "r_result",
]

SYMBOL = "BTCUSDT"
WAIT_WINDOW_BARS = 4
MIN_STOP_DISTANCE_PCT = 0.70


def _num(value: Any) -> float | None:
    try:
        if value in {"", None}:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_time(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _iso_from_ms(value: int) -> str:
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()


def _round(value: Any, digits: int = 8) -> str:
    number = _num(value)
    if number is None:
        return ""
    return str(round(number, digits))


def _read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return [{field: row.get(field, "") for field in FIELDS} for row in reader]


def _write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in FIELDS})


def _latest_signal_plan(path: Path, timestamp: str) -> dict[str, str]:
    if not path.exists():
        return {}
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        rows = [row for row in csv.DictReader(f) if row.get("symbol") == SYMBOL]
    if not rows:
        return {}
    exact = [row for row in rows if row.get("timestamp") == timestamp]
    return exact[-1] if exact else rows[-1]


def _fetch_recent_15m() -> list[dict[str, float | int]]:
    client = BinanceFuturesClient()
    result = client.get_klines(SYMBOL, "15m", 20)
    if not result.get("ok") or not isinstance(result.get("data"), list):
        return []
    return parse_klines(result["data"])


def _direction(decision_item: dict[str, Any]) -> str:
    if decision_item.get("allow_long"):
        return "long"
    if decision_item.get("allow_short"):
        return "short"
    return ""


def _bollinger_position(price: float | None, tf15: dict[str, Any]) -> str:
    boll = tf15.get("bollinger", {})
    upper = _num(boll.get("upper"))
    middle = _num(boll.get("middle"))
    lower = _num(boll.get("lower"))
    if price is None or upper is None or middle is None or lower is None:
        return "missing"
    if price > upper:
        return "above_upper"
    if price < lower:
        return "below_lower"
    if price >= middle:
        return "upper_half"
    return "lower_half"


def _candidate_allowed(snapshot: dict[str, Any], decision: dict[str, Any], plan: dict[str, str]) -> tuple[bool, str]:
    symbol_data = snapshot.get("symbols", {}).get(SYMBOL, {})
    decision_item = decision.get("symbols", {}).get(SYMBOL, {})
    direction = _direction(decision_item)
    if not direction:
        return False, "no BTC trade direction"

    entry = _num(plan.get("entry_price") or symbol_data.get("price", {}).get("last"))
    stop = _num(plan.get("stop_loss"))
    if entry is None or stop is None:
        return False, "missing trade plan"
    stop_distance = abs(entry - stop) / entry * 100
    if stop_distance < MIN_STOP_DISTANCE_PCT:
        return False, "stop distance below 0.70%"

    timestamp = _parse_time(str(snapshot.get("generated_at", "")))
    hour = timestamp.hour if timestamp else None
    if hour in {16, 17, 18, 19}:
        return False, "excluded by rule A"
    if hour in {8, 9, 10, 11}:
        return False, "excluded by rule B"
    if stop_distance < 0.10:
        return False, "excluded by rule C"

    structures = decision_item.get("structures", {})
    pattern = f"{structures.get('15m')}/{structures.get('1h')}/{structures.get('4h')}"
    if pattern in {"bullish/neutral/bearish", "bearish/bullish/bullish"}:
        return False, "excluded by rule E"

    tf15 = symbol_data.get("timeframes", {}).get("15m", {})
    boll_pos = _bollinger_position(entry, tf15)
    if direction == "long" and boll_pos == "above_upper":
        return False, "excluded by rule F"
    return True, ""


def _new_candidate_row(snapshot: dict[str, Any], decision: dict[str, Any], plan: dict[str, str], latest_kline: dict[str, float | int]) -> dict[str, Any] | None:
    decision_item = decision.get("symbols", {}).get(SYMBOL, {})
    direction = _direction(decision_item)
    signal_price = _num(plan.get("entry_price") or snapshot.get("symbols", {}).get(SYMBOL, {}).get("price", {}).get("last"))
    stop_loss = _num(plan.get("stop_loss"))
    take_profit = _num(plan.get("take_profit"))
    rr = _num(plan.get("risk_reward"))
    if not direction or signal_price is None or stop_loss is None or take_profit is None or rr is None:
        return None
    body_mid = (float(latest_kline["open"]) + float(latest_kline["close"])) / 2
    return {
        "timestamp": snapshot.get("generated_at", ""),
        "symbol": SYMBOL,
        "direction": direction,
        "signal_price": _round(signal_price),
        "body_mid_entry": _round(body_mid),
        "wait_window_bars": WAIT_WINDOW_BARS,
        "stop_loss": _round(stop_loss),
        "take_profit": _round(take_profit),
        "risk_reward": _round(rr, 4),
        "status": "waiting",
        "filled_price": "",
        "result": "",
        "r_result": "",
    }


def _bars_elapsed(start: str, latest_close_time: str) -> int:
    start_dt = _parse_time(start)
    latest_dt = _parse_time(latest_close_time)
    if not start_dt or not latest_dt:
        return 0
    return int((latest_dt - start_dt).total_seconds() // (15 * 60))


def _touches_entry(row: dict[str, str], kline: dict[str, float | int]) -> bool:
    entry = _num(row.get("body_mid_entry"))
    if entry is None:
        return False
    high = float(kline["high"])
    low = float(kline["low"])
    return low <= entry <= high


def _update_active_row(row: dict[str, str], latest_kline: dict[str, float | int]) -> dict[str, str]:
    status = row.get("status", "")
    latest_time = _iso_from_ms(int(latest_kline["close_time"]))
    if status == "waiting":
        if _touches_entry(row, latest_kline):
            row["status"] = "filled"
            row["filled_price"] = row.get("body_mid_entry", "")
        elif _bars_elapsed(row.get("timestamp", ""), latest_time) > WAIT_WINDOW_BARS:
            row["status"] = "expired"
            row["result"] = "expired"
            row["r_result"] = "0"
        return row

    if status == "filled":
        stop = _num(row.get("stop_loss"))
        take = _num(row.get("take_profit"))
        if stop is None or take is None:
            return row
        high = float(latest_kline["high"])
        low = float(latest_kline["low"])
        direction = row.get("direction")
        if direction == "long":
            hit_sl = low <= stop
            hit_tp = high >= take
        else:
            hit_sl = high >= stop
            hit_tp = low <= take
        # Observation-only conservative ordering.
        if hit_sl:
            row["status"] = "sl"
            row["result"] = "sl"
            row["r_result"] = "-1"
        elif hit_tp:
            row["status"] = "tp"
            row["result"] = "tp"
            row["r_result"] = row.get("risk_reward", "2.5")
    return row


def update_candidate_observer(snapshot: dict[str, Any], decision: dict[str, Any], out_dir: Path | None = None) -> dict[str, Any]:
    out = out_dir or output_dir()
    observer_path = out / "candidate_observer.csv"
    signal_history_path = out / "signal_history.csv"
    rows = _read_rows(observer_path)
    recent = _fetch_recent_15m()
    if not recent:
        _write_rows(observer_path, rows)
        return {"path": str(observer_path), "updated": 0, "created": 0, "latest": rows[-1] if rows else {}}

    latest_kline = recent[-1]
    updated = 0
    rows = [_update_active_row(row, latest_kline) for row in rows]
    updated = len([row for row in rows if row.get("status") in {"filled", "tp", "sl", "expired"}])

    timestamp = str(snapshot.get("generated_at", ""))
    existing_keys = {(row.get("timestamp"), row.get("symbol")) for row in rows}
    created = 0
    if (timestamp, SYMBOL) not in existing_keys:
        plan = _latest_signal_plan(signal_history_path, timestamp)
        allowed, _reason = _candidate_allowed(snapshot, decision, plan)
        if allowed:
            new_row = _new_candidate_row(snapshot, decision, plan, latest_kline)
            if new_row:
                rows.append(new_row)
                created = 1

    _write_rows(observer_path, rows)
    return {"path": str(observer_path), "updated": updated, "created": created, "latest": rows[-1] if rows else {}}
