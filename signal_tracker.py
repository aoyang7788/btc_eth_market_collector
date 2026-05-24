from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any


HORIZONS = {
    "after_1h_return_pct": 1,
    "after_4h_return_pct": 4,
    "after_24h_return_pct": 24,
    "after_72h_return_pct": 72,
    "after_7d_return_pct": 168,
}

BASE_FIELDS = [
    "timestamp",
    "symbol",
    "action",
    "price",
    "risk_level",
    "reason",
    "after_1h_return_pct",
    "after_4h_return_pct",
    "after_24h_return_pct",
    "after_72h_return_pct",
    "after_7d_return_pct",
]

EXTRA_FIELDS = [
    "structure_15m",
    "structure_1h",
    "structure_4h",
    "three_period_consistency",
]

FIELDS = BASE_FIELDS + EXTRA_FIELDS


def parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def round_pct(value: float | None) -> float | None:
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
        price = data.get("price", {}).get("last")
        try:
            if price is not None:
                result[symbol] = float(price)
        except (TypeError, ValueError):
            continue
    return result


def _build_rows(decision: dict[str, Any]) -> list[dict[str, Any]]:
    timestamp = decision.get("generated_at", "")
    rows = []
    for symbol, data in decision.get("symbols", {}).items():
        structures = data.get("structures", {})
        rows.append(
            {
                "timestamp": timestamp,
                "symbol": symbol,
                "action": data.get("suggested_action", ""),
                "price": data.get("price", ""),
                "risk_level": data.get("risk_level", ""),
                "reason": " | ".join(data.get("reason", [])),
                "after_1h_return_pct": "",
                "after_4h_return_pct": "",
                "after_24h_return_pct": "",
                "after_72h_return_pct": "",
                "after_7d_return_pct": "",
                "structure_15m": structures.get("15m", ""),
                "structure_1h": structures.get("1h", ""),
                "structure_4h": structures.get("4h", ""),
                "three_period_consistency": data.get("three_period_consistency", ""),
            }
        )
    return rows


def update_signal_history(snapshot: dict[str, Any], decision: dict[str, Any], history_path: Path) -> list[dict[str, Any]]:
    rows = read_history(history_path)
    prices = _price_map(snapshot)
    current_time = parse_iso(snapshot.get("generated_at", "")) or now_utc()

    for row in rows:
        timestamp = parse_iso(row.get("timestamp", ""))
        symbol = row.get("symbol", "")
        if not timestamp or symbol not in prices:
            continue
        try:
            entry_price = float(row.get("price", ""))
        except (TypeError, ValueError):
            continue
        if entry_price <= 0:
            continue

        elapsed_hours = (current_time - timestamp.astimezone(timezone.utc)).total_seconds() / 3600
        current_price = prices[symbol]
        raw_return = round_pct((current_price - entry_price) / entry_price * 100)
        for field, hours in HORIZONS.items():
            if row.get(field) in {"", None} and elapsed_hours >= hours:
                row[field] = raw_return

    existing_keys = {(row.get("timestamp"), row.get("symbol")) for row in rows}
    for new_row in _build_rows(decision):
        key = (new_row.get("timestamp"), new_row.get("symbol"))
        if key not in existing_keys:
            rows.append(new_row)
            existing_keys.add(key)

    write_history(history_path, rows)
    return rows


def _float_values(rows: list[dict[str, Any]], field: str) -> list[float]:
    values = []
    for row in rows:
        try:
            value = row.get(field, "")
            if value not in {"", None}:
                values.append(float(value))
        except (TypeError, ValueError):
            continue
    return values


def _latest_available_return(row: dict[str, Any]) -> float | None:
    for field in ["after_7d_return_pct", "after_72h_return_pct", "after_24h_return_pct", "after_4h_return_pct", "after_1h_return_pct"]:
        value = row.get(field, "")
        try:
            if value not in {"", None}:
                return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _favorable_return(row: dict[str, Any]) -> float | None:
    raw = _latest_available_return(row)
    if raw is None:
        return None
    if row.get("action") == "LOOK_FOR_SHORT":
        return -raw
    return raw


def _max_favorable(row: dict[str, Any]) -> float | None:
    values = []
    for field in HORIZONS:
        try:
            value = row.get(field, "")
            if value not in {"", None}:
                raw = float(value)
                values.append(-raw if row.get("action") == "LOOK_FOR_SHORT" else raw)
        except (TypeError, ValueError):
            continue
    if not values:
        return None
    return max(values)


def _max_adverse(row: dict[str, Any]) -> float | None:
    values = []
    for field in HORIZONS:
        try:
            value = row.get(field, "")
            if value not in {"", None}:
                raw = float(value)
                values.append(raw if row.get("action") == "LOOK_FOR_SHORT" else -raw)
        except (TypeError, ValueError):
            continue
    if not values:
        return None
    return max(values)


def _action_stats(rows: list[dict[str, Any]], action: str) -> dict[str, Any]:
    action_rows = [row for row in rows if row.get("action") == action]
    if action in {"WAIT", "NO_TRADE"}:
        return {"count": len(action_rows)}

    favorable = [value for value in (_favorable_return(row) for row in action_rows) if value is not None]
    max_favorable = [value for value in (_max_favorable(row) for row in action_rows) if value is not None]
    max_adverse = [value for value in (_max_adverse(row) for row in action_rows) if value is not None]
    wins = [value for value in favorable if value > 0]
    return {
        "count": len(action_rows),
        "resolved_count": len(favorable),
        "win_rate": round(len(wins) / len(favorable) * 100, 4) if favorable else None,
        "average_favorable_return_pct": round(mean(favorable), 6) if favorable else None,
        "max_favorable_return_pct": round(max(max_favorable), 6) if max_favorable else None,
        "max_adverse_move_pct": round(max(max_adverse), 6) if max_adverse else None,
    }


def _combo_stats(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        combo = f"{row.get('structure_15m')}/{row.get('structure_1h')}/{row.get('structure_4h')}|{row.get('three_period_consistency')}"
        groups.setdefault(combo, []).append(row)
    result = []
    for combo, combo_rows in groups.items():
        favorable = [value for value in (_favorable_return(row) for row in combo_rows if row.get("action") in {"LOOK_FOR_LONG", "LOOK_FOR_SHORT"}) if value is not None]
        wins = [value for value in favorable if value > 0]
        result.append(
            {
                "combo": combo,
                "count": len(combo_rows),
                "resolved_count": len(favorable),
                "win_rate": round(len(wins) / len(favorable) * 100, 4) if favorable else None,
                "average_favorable_return_pct": round(mean(favorable), 6) if favorable else None,
            }
        )
    return sorted(result, key=lambda item: (item["resolved_count"], item["count"]), reverse=True)


def build_signal_statistics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total_signals = len(rows)
    return {
        "total_signals": total_signals,
        "sample_size_note": "需要累计100次以上信号后再评估稳定优势" if total_signals < 100 else "样本数已达到100次以上，可开始评估稳定性",
        "actions": {
            "LOOK_FOR_LONG": _action_stats(rows, "LOOK_FOR_LONG"),
            "LOOK_FOR_SHORT": _action_stats(rows, "LOOK_FOR_SHORT"),
            "WAIT": _action_stats(rows, "WAIT"),
            "NO_TRADE": _action_stats(rows, "NO_TRADE"),
        },
        "cycle_combo_stats": _combo_stats(rows),
    }


def write_statistics_json(stats: dict[str, Any], path: Path) -> None:
    path.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
