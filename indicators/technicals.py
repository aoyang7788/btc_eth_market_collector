from __future__ import annotations

from math import sqrt
from statistics import mean
from typing import Any


def safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def round_value(value: float | None, digits: int = 6) -> float | None:
    if value is None:
        return None
    return round(value, digits)


def parse_klines(raw: list[list[Any]]) -> list[dict[str, float | int]]:
    parsed = []
    for item in raw:
        parsed.append(
            {
                "open_time": int(item[0]),
                "open": float(item[1]),
                "high": float(item[2]),
                "low": float(item[3]),
                "close": float(item[4]),
                "volume": float(item[5]),
                "close_time": int(item[6]),
            }
        )
    return parsed


def sma(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    return mean(values[-period:])


def ema_series(values: list[float], period: int) -> list[float] | None:
    if len(values) < period:
        return None
    alpha = 2 / (period + 1)
    result = [mean(values[:period])]
    for value in values[period:]:
        result.append((value - result[-1]) * alpha + result[-1])
    return result


def ema_latest(values: list[float], period: int) -> float | None:
    series = ema_series(values, period)
    if not series:
        return None
    return series[-1]


def bollinger(values: list[float], period: int = 20, mult: float = 2.0) -> dict[str, float | None]:
    if len(values) < period:
        return {"upper": None, "middle": None, "lower": None}
    window = values[-period:]
    middle = mean(window)
    variance = sum((x - middle) ** 2 for x in window) / period
    stdev = sqrt(variance)
    return {
        "upper": round_value(middle + mult * stdev),
        "middle": round_value(middle),
        "lower": round_value(middle - mult * stdev),
    }


def macd(values: list[float], fast: int = 12, slow: int = 26, signal_period: int = 9) -> dict[str, float | None]:
    if len(values) < slow + signal_period:
        return {"macd": None, "signal": None, "histogram": None}
    fast_series = ema_series(values, fast)
    slow_series = ema_series(values, slow)
    if not fast_series or not slow_series:
        return {"macd": None, "signal": None, "histogram": None}
    offset = len(fast_series) - len(slow_series)
    macd_values = [fast_series[i + offset] - slow_series[i] for i in range(len(slow_series))]
    signal_values = ema_series(macd_values, signal_period)
    if not signal_values:
        return {"macd": None, "signal": None, "histogram": None}
    macd_latest = macd_values[-1]
    signal_latest = signal_values[-1]
    return {
        "macd": round_value(macd_latest),
        "signal": round_value(signal_latest),
        "histogram": round_value(macd_latest - signal_latest),
    }


def volume_change(klines: list[dict[str, float | int]]) -> dict[str, float | None]:
    if len(klines) < 21:
        return {"current": None, "avg20": None, "ratio": None}
    current = float(klines[-1]["volume"])
    avg20 = mean(float(k["volume"]) for k in klines[-21:-1])
    ratio = current / avg20 if avg20 else None
    return {"current": round_value(current), "avg20": round_value(avg20), "ratio": round_value(ratio)}


def timeframe_snapshot(klines: list[dict[str, float | int]] | None) -> dict[str, Any]:
    empty = {
        "structure": "missing",
        "ema5": None,
        "ema13": None,
        "bollinger": {"upper": None, "middle": None, "lower": None},
        "macd": {"macd": None, "signal": None, "histogram": None},
        "volume_change": {"current": None, "avg20": None, "ratio": None},
    }
    if not klines or len(klines) < 35:
        return empty
    closes = [float(k["close"]) for k in klines]
    latest_close = closes[-1]
    ema5 = ema_latest(closes, 5)
    ema13 = ema_latest(closes, 13)
    if ema5 is None or ema13 is None:
        structure = "missing"
    elif ema5 > ema13 and latest_close > ema13:
        structure = "bullish"
    elif ema5 < ema13 and latest_close < ema13:
        structure = "bearish"
    else:
        structure = "neutral"
    return {
        "structure": structure,
        "ema5": round_value(ema5),
        "ema13": round_value(ema13),
        "bollinger": bollinger(closes),
        "macd": macd(closes),
        "volume_change": volume_change(klines),
    }


def daily_ma(klines: list[dict[str, float | int]] | None) -> dict[str, float | None]:
    if not klines:
        return {"ma50": None, "ma200": None}
    closes = [float(k["close"]) for k in klines]
    return {"ma50": round_value(sma(closes, 50)), "ma200": round_value(sma(closes, 200))}
