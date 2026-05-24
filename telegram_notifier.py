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


def build_telegram_message(decision: dict[str, Any] | None = None) -> str:
    data = decision or load_decision()
    if not data:
        return "BTC/ETH 市场分析完成，但 market_decision.json 暂不可读。"

    lines = ["BTC/ETH 市场分析完成", "", f"时间：{_fmt(data.get('generated_at'))}", ""]
    for symbol in ["BTCUSDT", "ETHUSDT"]:
        item = data.get("symbols", {}).get(symbol, {})
        structures = item.get("structures", {})
        lines.extend(
            [
                symbol,
                f"价格：{_fmt(item.get('price'))}",
                f"15m/1h/4h：{_fmt(structures.get('15m'))} / {_fmt(structures.get('1h'))} / {_fmt(structures.get('4h'))}",
                f"一致性：{_fmt(item.get('three_period_consistency'))}",
                f"风险等级：{_fmt(item.get('risk_level'))}",
                f"建议动作：{_fmt(item.get('suggested_action'))}",
                f"允许交易：{_fmt(item.get('allow_trade'))}",
                "",
            ]
        )
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
    return send_telegram_message("BTC/ETH Market Collector Telegram 推送测试成功")
