from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import requests

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

from config import BASE_DIR, REQUEST_TIMEOUT_SECONDS, output_dir


if load_dotenv:
    load_dotenv(BASE_DIR / ".env")


LOG_DIR = BASE_DIR / "logs"
TELEGRAM_LOG_PATH = LOG_DIR / "telegram.log"


def setup_telegram_logger() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("market_collector.telegram")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not any(isinstance(handler, logging.FileHandler) and Path(handler.baseFilename) == TELEGRAM_LOG_PATH for handler in logger.handlers):
        handler = logging.FileHandler(TELEGRAM_LOG_PATH, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    return logger


def _mask_token(token: str) -> str:
    if not token:
        return ""
    if len(token) <= 10:
        return "****"
    return f"{token[:6]}****{token[-4:]}"


def _num(value: Any) -> float | None:
    try:
        if value in {"", None}:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt(value: Any) -> str:
    if value is None or value == "":
        return "缺失"
    if isinstance(value, bool):
        return "是" if value else "否"
    return str(value)


def _fmt_price(value: Any) -> str:
    number = _num(value)
    if number is None:
        return "缺失"
    return f"{number:.2f}".rstrip("0").rstrip(".")


def _fmt_percent(value: Any) -> str:
    number = _num(value)
    if number is None:
        return "缺失"
    return f"{number * 100:.4f}".rstrip("0").rstrip(".") + "%"


def _fmt_large(value: Any) -> str:
    number = _num(value)
    if number is None:
        return "缺失"
    if abs(number) >= 100000000:
        return f"{number / 100000000:.2f}亿"
    if abs(number) >= 10000:
        return f"{number / 10000:.2f}万"
    return f"{number:.2f}".rstrip("0").rstrip(".")


def load_decision(decision_path: Path | None = None) -> dict[str, Any] | None:
    path = decision_path or (output_dir() / "market_decision.json")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def load_snapshot(snapshot_path: Path | None = None) -> dict[str, Any] | None:
    path = snapshot_path or (output_dir() / "market_snapshot.json")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _direction(value: Any) -> str:
    return {
        "bullish": "多头",
        "bearish": "空头",
        "neutral": "中性",
        "missing": "缺失",
    }.get(str(value), _fmt(value))


def _risk(value: Any) -> str:
    return {
        "LOW": "低风险",
        "MEDIUM": "中风险",
        "HIGH": "高风险",
    }.get(str(value), _fmt(value))


def _consistency(value: Any) -> str:
    return {
        "bullish_aligned": "多周期多头共振",
        "bearish_aligned": "多周期空头共振",
        "bullish_pullback": "多头趋势回踩",
        "bearish_pullback": "空头趋势反抽",
        "mixed_neutral": "多周期中性混合",
        "conflict": "多周期冲突",
        "missing": "缺失",
    }.get(str(value), _fmt(value))


def _macd(macd: dict[str, Any]) -> str:
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


def _bollinger(price: Any, bollinger: dict[str, Any]) -> str:
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


def _advice(decision_item: dict[str, Any]) -> str:
    if decision_item.get("allow_long"):
        return "允许做多"
    if decision_item.get("allow_short"):
        return "允许做空"
    return "观望等待"


def _score_direction(decision_item: dict[str, Any]) -> str | None:
    advice = _advice(decision_item)
    if advice == "允许做多":
        return "long"
    if advice == "允许做空":
        return "short"
    structures = decision_item.get("structures", {})
    if structures.get("4h") == "bullish":
        return "long"
    if structures.get("4h") == "bearish":
        return "short"
    return None


def _ema_score(snapshot_item: dict[str, Any], direction: str | None) -> int:
    if direction is None:
        return 0
    weights = {"4h": 18, "1h": 14, "15m": 8}
    total = 0
    for tf, weight in weights.items():
        data = snapshot_item.get("timeframes", {}).get(tf, {})
        ema5 = _num(data.get("ema5"))
        ema13 = _num(data.get("ema13"))
        price = _num(snapshot_item.get("price", {}).get("last"))
        if ema5 is None or ema13 is None or price is None:
            continue
        if direction == "long" and ema5 > ema13 and price >= ema13:
            total += weight
        if direction == "short" and ema5 < ema13 and price <= ema13:
            total += weight
    return total


def _bb_score(snapshot_item: dict[str, Any], direction: str | None) -> int:
    if direction is None:
        return 0
    price = _num(snapshot_item.get("price", {}).get("last"))
    boll = snapshot_item.get("timeframes", {}).get("4h", {}).get("bollinger", {})
    upper = _num(boll.get("upper"))
    middle = _num(boll.get("middle"))
    lower = _num(boll.get("lower"))
    if price is None or upper is None or middle is None or lower is None:
        return 0
    if direction == "long":
        if middle <= price <= upper:
            return 25
        if lower <= price < middle:
            return 18
        if price > upper:
            return 12
    if direction == "short":
        if lower <= price <= middle:
            return 25
        if middle < price <= upper:
            return 18
        if price < lower:
            return 12
    return 0


def _support_resistance_score(snapshot_item: dict[str, Any], direction: str | None) -> int:
    if direction is None:
        return 0
    price = _num(snapshot_item.get("price", {}).get("last"))
    ranges = snapshot_item.get("timeframes", {}).get("15m", {}).get("recent_range", {})
    high = _num(ranges.get("high"))
    low = _num(ranges.get("low"))
    if price is None or high is None or low is None or high <= low:
        return 0
    span = high - low
    if direction == "long":
        position = (price - low) / span
        if 0.2 <= position <= 0.85:
            return 20
        if 0 <= position < 0.2:
            return 14
    if direction == "short":
        position = (high - price) / span
        if 0.2 <= position <= 0.85:
            return 20
        if 0 <= position < 0.2:
            return 14
    return 8


def _funding_score(snapshot_item: dict[str, Any], direction: str | None) -> int:
    funding = _num(snapshot_item.get("derivatives", {}).get("funding_rate"))
    if funding is None or direction is None:
        return 0
    if abs(funding) <= 0.0005:
        return 5
    if direction == "long" and funding < 0:
        return 5
    if direction == "short" and funding > 0:
        return 5
    return 2


def _long_short_score(snapshot_item: dict[str, Any], direction: str | None) -> int:
    ratio = _num(snapshot_item.get("derivatives", {}).get("long_short_ratio"))
    if ratio is None or direction is None:
        return 0
    if 0.8 <= ratio <= 1.5:
        return 5
    if direction == "long" and ratio < 0.8:
        return 4
    if direction == "short" and ratio > 1.5:
        return 4
    return 2


def _oi_score(snapshot_item: dict[str, Any], direction: str | None) -> int:
    change = _num(snapshot_item.get("derivatives", {}).get("open_interest_change"))
    if change is None or direction is None:
        return 0
    if change > 0:
        return 5
    if abs(change) <= 0.5:
        return 3
    return 1


def _score(snapshot_item: dict[str, Any], decision_item: dict[str, Any]) -> int:
    direction = _score_direction(decision_item)
    score = (
        _ema_score(snapshot_item, direction)
        + _bb_score(snapshot_item, direction)
        + _support_resistance_score(snapshot_item, direction)
        + _funding_score(snapshot_item, direction)
        + _long_short_score(snapshot_item, direction)
        + _oi_score(snapshot_item, direction)
    )
    return max(0, min(100, score))


def _reasons(snapshot_item: dict[str, Any], decision_item: dict[str, Any]) -> list[str]:
    reasons = []
    tf4h = snapshot_item.get("timeframes", {}).get("4h", {})
    price = _num(snapshot_item.get("price", {}).get("last"))
    derivatives = snapshot_item.get("derivatives", {})
    ema5 = _num(tf4h.get("ema5"))
    ema13 = _num(tf4h.get("ema13"))
    boll = tf4h.get("bollinger", {})
    middle = _num(boll.get("middle"))
    oi_change = _num(derivatives.get("open_interest_change"))
    if ema5 is not None and ema13 is not None:
        if ema5 > ema13:
            reasons.append("① EMA5上穿EMA13，多头结构占优")
        elif ema5 < ema13:
            reasons.append("① EMA5低于EMA13，空头结构占优")
    if price is not None and middle is not None:
        if price >= middle:
            reasons.append("② 价格位于布林带中轨上方")
        else:
            reasons.append("② 价格位于布林带中轨下方")
    if decision_item.get("three_period_consistency") in {"bullish_aligned", "bearish_aligned"}:
        reasons.append("③ 主周期结构共振")
    if oi_change is not None and oi_change > 0:
        reasons.append("④ OI持续增长")
    elif oi_change is not None and oi_change < 0:
        reasons.append("④ OI回落")
    if not reasons:
        reasons.append("① 当前信号条件未形成明显优势")
    return reasons


def _symbol_block(symbol: str, snapshot: dict[str, Any], decision: dict[str, Any]) -> list[str]:
    snapshot_item = snapshot.get("symbols", {}).get(symbol, {})
    decision_item = decision.get("symbols", {}).get(symbol, {})
    tf4h = snapshot_item.get("timeframes", {}).get("4h", {})
    derivatives = snapshot_item.get("derivatives", {})
    structures = decision_item.get("structures", {})
    price = snapshot_item.get("price", {}).get("last")
    reasons = _reasons(snapshot_item, decision_item)

    return [
        "━━━━━━━━━━━━━━",
        "",
        symbol,
        "",
        "当前价格：",
        _fmt_price(price),
        "",
        "EMA5：",
        _fmt_price(tf4h.get("ema5")),
        "",
        "EMA13：",
        _fmt_price(tf4h.get("ema13")),
        "",
        "布林带：",
        _bollinger(price, tf4h.get("bollinger", {})),
        "",
        "辅助参考：",
        "",
        "EMA50：",
        _fmt_price(tf4h.get("ema50")),
        "",
        "EMA200：",
        _fmt_price(tf4h.get("ema200")),
        "",
        "MACD：",
        _macd(tf4h.get("macd", {})),
        "",
        "资金费率：",
        _fmt_percent(derivatives.get("funding_rate")),
        "",
        "多空比：",
        _fmt(derivatives.get("long_short_ratio")),
        "",
        "持仓量：",
        _fmt_large(derivatives.get("open_interest")),
        "",
        "15分钟：",
        _direction(structures.get("15m")),
        "",
        "1小时：",
        _direction(structures.get("1h")),
        "",
        "4小时：",
        _direction(structures.get("4h")),
        "",
        "多周期结构：",
        _consistency(decision_item.get("three_period_consistency")),
        "",
        "综合评分：",
        f"{_score(snapshot_item, decision_item)}分",
        "",
        "风险等级：",
        _risk(decision_item.get("risk_level")),
        "",
        "建议：",
        _advice(decision_item),
        "",
        "允许交易：",
        "是" if decision_item.get("allow_trade") else "否",
        "",
        "原因：",
        "",
        *reasons,
        "",
    ]


def build_telegram_message(decision: dict[str, Any] | None = None, snapshot: dict[str, Any] | None = None) -> str:
    data = decision or load_decision()
    snapshot_data = snapshot or load_snapshot()
    if not data:
        return "BTC/ETH 市场分析完成，但 market_decision.json 暂不可读。"
    if not snapshot_data:
        return "BTC/ETH 市场分析完成，但 market_snapshot.json 暂不可读。"

    lines = ["📊 BTC/ETH市场分析完成", "", "时间：", _fmt(data.get("generated_at")), ""]
    for symbol in ["BTCUSDT", "ETHUSDT"]:
        lines.extend(_symbol_block(symbol, snapshot_data, data))
    return "\n".join(lines).strip()


def send_telegram_message(text: str) -> dict[str, Any]:
    logger = setup_telegram_logger()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token:
        logger.warning("TELEGRAM_SKIP missing TELEGRAM_BOT_TOKEN")
        return {"ok": False, "error": "missing TELEGRAM_BOT_TOKEN"}
    if not chat_id:
        logger.warning("TELEGRAM_SKIP missing TELEGRAM_CHAT_ID token=%s", _mask_token(token))
        return {"ok": False, "error": "missing TELEGRAM_CHAT_ID"}

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("ok"):
            logger.info("TELEGRAM_SENT chat_id=%s token=%s", chat_id, _mask_token(token))
            return {"ok": True, "data": payload}
        logger.warning("TELEGRAM_FAILED chat_id=%s error=%s", chat_id, payload.get("description", "unknown"))
        return {"ok": False, "error": payload.get("description", "unknown")}
    except requests.RequestException as exc:
        logger.warning("TELEGRAM_ERROR chat_id=%s error_type=%s", chat_id, type(exc).__name__)
        return {"ok": False, "error": f"{type(exc).__name__}: request failed"}
    except ValueError:
        logger.warning("TELEGRAM_ERROR chat_id=%s error=invalid_json", chat_id)
        return {"ok": False, "error": "invalid json response"}


def send_analysis_update() -> dict[str, Any]:
    return send_telegram_message(build_telegram_message())


def send_test_message() -> dict[str, Any]:
    return send_telegram_message("[测试推送]\n" + build_telegram_message())
