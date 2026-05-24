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


def _score(snapshot_item: dict[str, Any], decision_item: dict[str, Any]) -> int:
    score = 50
    advice = _advice(decision_item)
    consistency = decision_item.get("three_period_consistency")
    risk = decision_item.get("risk_level")
    structures = decision_item.get("structures", {})
    tf4h = snapshot_item.get("timeframes", {}).get("4h", {})
    price = _num(snapshot_item.get("price", {}).get("last"))
    ema50 = _num(tf4h.get("ema50"))
    ema200 = _num(tf4h.get("ema200"))
    hist = _num(tf4h.get("macd", {}).get("histogram"))

    if advice in {"允许做多", "允许做空"}:
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
    if hist is None:
        score -= 5
    elif (advice == "允许做多" and hist > 0) or (advice == "允许做空" and hist < 0):
        score += 5
    if price is None or ema50 is None or ema200 is None:
        score -= 5
    elif advice == "允许做多" and price >= ema50 >= ema200:
        score += 5
    elif advice == "允许做空" and price <= ema50 <= ema200:
        score += 5
    if risk == "LOW":
        score += 10
    elif risk == "HIGH":
        score -= 20
    return max(0, min(100, score))


def _reasons(snapshot_item: dict[str, Any], decision_item: dict[str, Any]) -> list[str]:
    reasons = []
    tf4h = snapshot_item.get("timeframes", {}).get("4h", {})
    derivatives = snapshot_item.get("derivatives", {})
    ema5 = _num(tf4h.get("ema5"))
    ema13 = _num(tf4h.get("ema13"))
    ema50 = _num(tf4h.get("ema50"))
    ema200 = _num(tf4h.get("ema200"))
    oi_change = _num(derivatives.get("open_interest_change"))
    if ema5 is not None and ema13 is not None and ema50 is not None:
        if ema5 > ema13 > ema50:
            reasons.append("① EMA多头排列")
        elif ema5 < ema13 < ema50:
            reasons.append("① EMA空头排列")
    if _macd(tf4h.get("macd", {})) == "金叉":
        reasons.append("② MACD金叉")
    elif _macd(tf4h.get("macd", {})) == "死叉":
        reasons.append("② MACD死叉")
    if decision_item.get("three_period_consistency") in {"bullish_aligned", "bearish_aligned"}:
        reasons.append("③ 多周期共振")
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
        "EMA50：",
        _fmt_price(tf4h.get("ema50")),
        "",
        "EMA200：",
        _fmt_price(tf4h.get("ema200")),
        "",
        "MACD：",
        _macd(tf4h.get("macd", {})),
        "",
        "布林带：",
        _bollinger(price, tf4h.get("bollinger", {})),
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
