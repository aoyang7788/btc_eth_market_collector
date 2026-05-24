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


def _fmt(value: Any) -> str:
    if value is None:
        return "missing"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


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


def _direction_label(value: Any) -> str:
    mapping = {
        "bullish": "多头",
        "bearish": "空头",
        "neutral": "中性",
        "missing": "missing",
    }
    return mapping.get(str(value), _fmt(value))


def _macd_state(macd: dict[str, Any]) -> str:
    hist = macd.get("histogram")
    try:
        hist_value = float(hist)
    except (TypeError, ValueError):
        return "missing"
    if hist_value > 0:
        return f"偏多 histogram={hist_value}"
    if hist_value < 0:
        return f"偏空 histogram={hist_value}"
    return "中性 histogram=0"


def _bollinger_position(price: Any, bollinger: dict[str, Any]) -> str:
    try:
        value = float(price)
        upper = float(bollinger.get("upper"))
        middle = float(bollinger.get("middle"))
        lower = float(bollinger.get("lower"))
    except (TypeError, ValueError):
        return "missing"
    if value > upper:
        return "上轨上方"
    if value < lower:
        return "下轨下方"
    if value >= middle:
        return "中轨至上轨"
    return "下轨至中轨"


def _advice(decision_item: dict[str, Any]) -> str:
    if decision_item.get("allow_long"):
        return "ALLOW_LONG"
    if decision_item.get("allow_short"):
        return "ALLOW_SHORT"
    return "WAIT"


def _score(snapshot_item: dict[str, Any], decision_item: dict[str, Any]) -> int:
    score = 50
    consistency = decision_item.get("three_period_consistency")
    risk = decision_item.get("risk_level")
    structures = decision_item.get("structures", {})
    action = _advice(decision_item)
    tf4h = snapshot_item.get("timeframes", {}).get("4h", {})
    macd_hist = tf4h.get("macd", {}).get("histogram")
    price = snapshot_item.get("price", {}).get("last")
    ema50 = tf4h.get("ema50")
    ema200 = tf4h.get("ema200")

    if decision_item.get("allow_trade"):
        score += 20
    else:
        score -= 10

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

    try:
        hist = float(macd_hist)
        if (action == "ALLOW_LONG" and hist > 0) or (action == "ALLOW_SHORT" and hist < 0):
            score += 5
        elif action != "WAIT":
            score -= 5
    except (TypeError, ValueError):
        score -= 5

    try:
        price_value = float(price)
        ema50_value = float(ema50)
        ema200_value = float(ema200)
        if action == "ALLOW_LONG" and price_value >= ema50_value >= ema200_value:
            score += 5
        elif action == "ALLOW_SHORT" and price_value <= ema50_value <= ema200_value:
            score += 5
    except (TypeError, ValueError):
        score -= 5

    if risk == "LOW":
        score += 10
    elif risk == "MEDIUM":
        score += 0
    elif risk == "HIGH":
        score -= 20

    return max(0, min(100, score))


def _why_text(decision_item: dict[str, Any]) -> tuple[str, str]:
    reasons = decision_item.get("reason", [])
    warnings = decision_item.get("warnings", [])
    if decision_item.get("allow_trade"):
        allowed = [
            f"建议动作={_advice(decision_item)}",
            f"三周期一致性={_fmt(decision_item.get('three_period_consistency'))}",
            f"风险等级={_fmt(decision_item.get('risk_level'))}",
        ]
        blocked = "无硬性禁止原因。"
        return "\n".join(f"- {item}" for item in allowed), blocked

    blocked_items = warnings[:]
    if not blocked_items:
        blocked_items = [
            f"建议动作为 {_advice(decision_item)}",
            f"三周期一致性={_fmt(decision_item.get('three_period_consistency'))}",
        ]
    if reasons:
        blocked_items.extend(reasons[:4])
    allowed = "无，当前未满足交易条件。"
    blocked = "\n".join(f"- {item}" for item in blocked_items[:8])
    return allowed, blocked


def _symbol_block(symbol: str, snapshot: dict[str, Any], decision: dict[str, Any]) -> list[str]:
    snapshot_item = snapshot.get("symbols", {}).get(symbol, {})
    decision_item = decision.get("symbols", {}).get(symbol, {})
    price = snapshot_item.get("price", {}).get("last")
    derivatives = snapshot_item.get("derivatives", {})
    tf = snapshot_item.get("timeframes", {})
    tf4h = tf.get("4h", {})
    structures = decision_item.get("structures", {})
    bollinger_position = _bollinger_position(price, tf4h.get("bollinger", {}))
    allowed_text, blocked_text = _why_text(decision_item)
    score = _score(snapshot_item, decision_item)

    return [
        "------------------------------",
        symbol,
        "",
        f"当前价格：{_fmt(price)}",
        "",
        "EMA（4h）",
        f"EMA5：{_fmt(tf4h.get('ema5'))}",
        f"EMA13：{_fmt(tf4h.get('ema13'))}",
        f"EMA50：{_fmt(tf4h.get('ema50'))}",
        f"EMA200：{_fmt(tf4h.get('ema200'))}",
        "",
        f"MACD状态：{_macd_state(tf4h.get('macd', {}))}",
        f"布林带位置：{bollinger_position}",
        "",
        f"资金费率：{_fmt(derivatives.get('funding_rate'))}",
        f"多空比：{_fmt(derivatives.get('long_short_ratio'))}",
        f"持仓量(OI)：{_fmt(derivatives.get('open_interest'))}",
        "",
        f"15分钟方向：{_direction_label(structures.get('15m'))}",
        f"1小时方向：{_direction_label(structures.get('1h'))}",
        f"4小时方向：{_direction_label(structures.get('4h'))}",
        "",
        f"综合评分：{score}/100",
        f"建议：{_advice(decision_item)}",
        f"风险等级：{_fmt(decision_item.get('risk_level'))}",
        "",
        "为什么允许交易：",
        allowed_text,
        "",
        "为什么不允许交易：",
        blocked_text,
        "",
    ]


def build_telegram_message(decision: dict[str, Any] | None = None, snapshot: dict[str, Any] | None = None) -> str:
    data = decision or load_decision()
    snapshot_data = snapshot or load_snapshot()
    if not data:
        return "BTC/ETH 市场分析完成，但 market_decision.json 暂不可读。"
    if not snapshot_data:
        return "BTC/ETH 市场分析完成，但 market_snapshot.json 暂不可读。"

    lines = ["BTC/ETH 三周期市场分析", f"时间：{_fmt(data.get('generated_at'))}", ""]
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

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        response = requests.post(
            url,
            json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
        ok = bool(payload.get("ok"))
        if ok:
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
    message = build_telegram_message()
    return send_telegram_message(message)


def send_test_message() -> dict[str, Any]:
    return send_telegram_message("[测试推送]\n" + build_telegram_message())
