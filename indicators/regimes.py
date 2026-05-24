from __future__ import annotations


def judge_decision(source_status: dict[str, str], timeframe_data: dict[str, dict]) -> dict:
    reason: list[str] = []
    structures = {
        "15m": timeframe_data.get("15m", {}).get("structure", "missing"),
        "1h": timeframe_data.get("1h", {}).get("structure", "missing"),
        "4h": timeframe_data.get("4h", {}).get("structure", "missing"),
    }

    is_bullish = structures["4h"] == "bullish" and structures["1h"] != "bearish"
    is_bearish = structures["4h"] == "bearish" and structures["1h"] != "bullish"

    critical_missing = {
        "binance_klines": "missing klines",
        "binance_funding": "funding rate missing",
        "binance_oi": "open interest missing",
        "binance_long_short_ratio": "long short ratio missing",
        "coinglass_liquidation_map": "missing liquidation map",
    }
    for key, msg in critical_missing.items():
        if source_status.get(key) != "ok":
            reason.append(msg)

    if any(value == "missing" for value in structures.values()):
        reason.append("timeframe structure missing")

    if "bullish" in structures.values() and "bearish" in structures.values():
        reason.append("timeframes conflict")

    return {
        "is_bullish_environment": bool(is_bullish),
        "is_bearish_environment": bool(is_bearish),
        "allow_open": False,
        "forbid_trade": bool(reason),
        "reason": sorted(set(reason)),
    }
