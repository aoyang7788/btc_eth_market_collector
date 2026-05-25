from __future__ import annotations

from typing import Any


ACTIONS = {"LOOK_FOR_LONG", "LOOK_FOR_SHORT", "WAIT", "NO_TRADE"}
OBSERVATION_ONLY_SYMBOLS = {"ETHUSDT"}


def _num(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _structure(symbol_data: dict[str, Any], timeframe: str) -> str:
    return symbol_data.get("timeframes", {}).get(timeframe, {}).get("structure", "missing")


def _missing_core(symbol_data: dict[str, Any]) -> list[str]:
    missing = []
    for tf in ["15m", "1h", "4h"]:
        data = symbol_data.get("timeframes", {}).get(tf, {})
        if data.get("structure") == "missing":
            missing.append(f"{tf} structure missing")
        if data.get("ema5") is None or data.get("ema13") is None:
            missing.append(f"{tf} EMA missing")
        boll = data.get("bollinger", {})
        if boll.get("upper") is None or boll.get("middle") is None or boll.get("lower") is None:
            missing.append(f"{tf} Bollinger missing")

    derivatives = symbol_data.get("derivatives", {})
    if derivatives.get("funding_rate") is None:
        missing.append("funding rate missing")
    if derivatives.get("open_interest") is None:
        missing.append("open interest missing")
    if derivatives.get("open_interest_change") is None:
        missing.append("open interest change missing")
    if derivatives.get("long_short_ratio") is None:
        missing.append("long short ratio missing")
    return sorted(set(missing))


def _three_period_consistency(s15: str, s1h: str, s4h: str) -> str:
    values = [s15, s1h, s4h]
    if "missing" in values:
        return "missing"
    if values == ["bullish", "bullish", "bullish"]:
        return "bullish_aligned"
    if values == ["bearish", "bearish", "bearish"]:
        return "bearish_aligned"
    if s4h == "bullish" and s1h in {"bullish", "neutral"} and s15 in {"neutral", "bearish"}:
        return "bullish_pullback"
    if s4h == "bearish" and s1h in {"bearish", "neutral"} and s15 in {"neutral", "bullish"}:
        return "bearish_pullback"
    if "bullish" in values and "bearish" in values:
        return "conflict"
    return "mixed_neutral"


def _bollinger_position(price: float | None, timeframe_data: dict[str, Any]) -> str:
    boll = timeframe_data.get("bollinger", {})
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


def _risk_level(reasons: list[str], consistency: str, derivatives: dict[str, Any]) -> str:
    if any("missing" in item for item in reasons):
        return "HIGH"
    if consistency == "conflict":
        return "HIGH"

    oi_change = _num(derivatives.get("open_interest_change"))
    long_short = _num(derivatives.get("long_short_ratio"))
    funding = _num(derivatives.get("funding_rate"))
    if oi_change is not None and abs(oi_change) >= 5:
        return "HIGH"
    if long_short is not None and (long_short >= 2.5 or long_short <= 0.4):
        return "HIGH"
    if funding is not None and abs(funding) >= 0.001:
        return "MEDIUM"
    if consistency in {"bullish_pullback", "bearish_pullback", "mixed_neutral"}:
        return "MEDIUM"
    return "LOW"


def evaluate_symbol(symbol: str, symbol_data: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    warnings: list[str] = []
    price = _num(symbol_data.get("price", {}).get("last"))
    derivatives = symbol_data.get("derivatives", {})
    tf_data = symbol_data.get("timeframes", {})

    s15 = _structure(symbol_data, "15m")
    s1h = _structure(symbol_data, "1h")
    s4h = _structure(symbol_data, "4h")
    consistency = _three_period_consistency(s15, s1h, s4h)

    for tf, structure in [("4h", s4h), ("1h", s1h), ("15m", s15)]:
        reasons.append(f"{tf} {structure}")

    if consistency != "missing":
        reasons.append(f"three timeframe consistency: {consistency}")

    missing = _missing_core(symbol_data)
    reasons.extend(missing)

    for tf in ["15m", "1h", "4h"]:
        hist = _num(tf_data.get(tf, {}).get("macd", {}).get("histogram"))
        if hist is not None:
            if hist > 0:
                reasons.append(f"{tf} MACD histogram positive")
            elif hist < 0:
                reasons.append(f"{tf} MACD histogram negative")
            else:
                reasons.append(f"{tf} MACD histogram flat")
        boll_pos = _bollinger_position(price, tf_data.get(tf, {}))
        if boll_pos != "missing":
            reasons.append(f"{tf} Bollinger position {boll_pos}")

    funding = _num(derivatives.get("funding_rate"))
    oi_change = _num(derivatives.get("open_interest_change"))
    long_short = _num(derivatives.get("long_short_ratio"))
    if funding is not None:
        reasons.append("funding positive" if funding > 0 else "funding negative" if funding < 0 else "funding neutral")
    if oi_change is not None:
        reasons.append("oi rising" if oi_change > 0 else "oi falling" if oi_change < 0 else "oi flat")
    if long_short is not None:
        if long_short > 1.2:
            reasons.append("long short ratio long biased")
        elif long_short < 0.8:
            reasons.append("long short ratio short biased")
        else:
            reasons.append("long short ratio balanced")

    long_conditions = [
        consistency in {"bullish_aligned", "bullish_pullback"},
        s4h == "bullish",
        s1h != "bearish",
    ]
    short_conditions = [
        consistency in {"bearish_aligned", "bearish_pullback"},
        s4h == "bearish",
        s1h != "bullish",
    ]

    has_missing = bool(missing)
    allow_long = all(long_conditions) and not has_missing and consistency != "conflict"
    allow_short = all(short_conditions) and not has_missing and consistency != "conflict"
    allow_trade = allow_long or allow_short

    if consistency == "conflict":
        warnings.append("timeframes conflict")
    if has_missing:
        warnings.append("core data missing")
    if allow_long and allow_short:
        warnings.append("long and short conflict")
        allow_long = False
        allow_short = False
        allow_trade = False

    if allow_long:
        action = "LOOK_FOR_LONG"
    elif allow_short:
        action = "LOOK_FOR_SHORT"
    elif has_missing or consistency == "conflict":
        action = "NO_TRADE"
    else:
        action = "WAIT"

    risk_level = _risk_level(reasons + warnings, consistency, derivatives)
    if action == "NO_TRADE":
        risk_level = "HIGH"

    return {
        "symbol": symbol,
        "price": symbol_data.get("price", {}).get("last"),
        "structures": {
            "15m": s15,
            "1h": s1h,
            "4h": s4h,
        },
        "three_period_consistency": consistency,
        "allow_long": bool(allow_long),
        "allow_short": bool(allow_short),
        "allow_trade": bool(allow_trade),
        "risk_level": risk_level,
        "suggested_action": action if action in ACTIONS else "NO_TRADE",
        "reason": sorted(set(reasons)),
        "warnings": sorted(set(warnings)),
        "inputs_used": [
            "EMA5",
            "EMA13",
            "Bollinger Bands",
            "Open Interest",
            "Funding Rate",
            "Long/Short Ratio",
            "辅助参考: MA50",
            "辅助参考: MA200",
            "辅助参考: MACD",
        ],
    }


def build_market_decision(snapshot: dict[str, Any]) -> dict[str, Any]:
    symbols = {}
    for symbol, symbol_data in snapshot.get("symbols", {}).items():
        decision = evaluate_symbol(symbol, symbol_data)
        if symbol in OBSERVATION_ONLY_SYMBOLS:
            decision["observation_only"] = True
            decision.pop("allow_long", None)
            decision.pop("allow_short", None)
            decision.pop("allow_trade", None)
            decision.pop("suggested_action", None)
        symbols[symbol] = decision
    return {
        "generated_at": snapshot.get("generated_at"),
        "source_snapshot": "market_snapshot.json",
        "mode": "decision_only_no_order_execution",
        "allowed_actions": sorted(ACTIONS),
        "symbols": symbols,
    }
