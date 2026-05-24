from __future__ import annotations

import csv
from pathlib import Path
from typing import Any


FIELDS = [
    "timestamp",
    "symbol",
    "price",
    "change_24h_pct",
    "structure_15m",
    "structure_1h",
    "structure_4h",
    "is_bullish_env",
    "is_bearish_env",
    "allow_open",
    "forbid_trade",
    "funding_rate",
    "open_interest",
    "oi_change",
    "long_short_ratio",
    "liquidation_map_status",
    "reason",
]


def write_signal_summary(snapshot: dict[str, Any], path: Path) -> None:
    rows = []
    generated_at = snapshot.get("generated_at")
    for symbol, data in snapshot.get("symbols", {}).items():
        rows.append(
            {
                "timestamp": generated_at,
                "symbol": symbol,
                "price": data.get("price", {}).get("last"),
                "change_24h_pct": data.get("price", {}).get("change_24h_pct"),
                "structure_15m": data.get("timeframes", {}).get("15m", {}).get("structure"),
                "structure_1h": data.get("timeframes", {}).get("1h", {}).get("structure"),
                "structure_4h": data.get("timeframes", {}).get("4h", {}).get("structure"),
                "is_bullish_env": data.get("decision", {}).get("is_bullish_environment"),
                "is_bearish_env": data.get("decision", {}).get("is_bearish_environment"),
                "allow_open": data.get("decision", {}).get("allow_open"),
                "forbid_trade": data.get("decision", {}).get("forbid_trade"),
                "funding_rate": data.get("derivatives", {}).get("funding_rate"),
                "open_interest": data.get("derivatives", {}).get("open_interest"),
                "oi_change": data.get("derivatives", {}).get("open_interest_change"),
                "long_short_ratio": data.get("derivatives", {}).get("long_short_ratio"),
                "liquidation_map_status": data.get("derivatives", {}).get("liquidation_map", {}).get("status"),
                "reason": "; ".join(data.get("decision", {}).get("reason", [])),
            }
        )
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
