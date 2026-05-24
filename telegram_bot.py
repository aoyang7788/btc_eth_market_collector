from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

try:
    from telegram import Update
    from telegram.ext import Application, CommandHandler, ContextTypes
except ImportError:  # pragma: no cover
    Update = None
    Application = None
    CommandHandler = None
    ContextTypes = None


BASE_DIR = Path(__file__).resolve().parent
MISSING_REPORT_TEXT = "报告尚未生成，请先运行 python main.py --once"


if load_dotenv:
    load_dotenv(BASE_DIR / ".env")

OUTPUT_DIR = BASE_DIR / os.getenv("OUTPUT_DIR", "outputs")

from health_monitor import format_health_text, read_status  # noqa: E402


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8-sig")
    except (FileNotFoundError, OSError):
        return None


def _fmt(value: Any) -> str:
    if value is None:
        return "missing"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _load_reports() -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    snapshot = _read_json(OUTPUT_DIR / "market_snapshot.json")
    decision = _read_json(OUTPUT_DIR / "market_decision.json")
    return snapshot, decision


def _symbol_snapshot(snapshot: dict[str, Any] | None, symbol: str) -> dict[str, Any] | None:
    return (snapshot or {}).get("symbols", {}).get(symbol)


def _symbol_decision(decision: dict[str, Any] | None, symbol: str) -> dict[str, Any] | None:
    return (decision or {}).get("symbols", {}).get(symbol)


def build_market_summary() -> str:
    snapshot, decision = _load_reports()
    if not snapshot or not decision:
        return MISSING_REPORT_TEXT

    lines = ["BTC/ETH 三周期市场简版总览", ""]
    for symbol in ["BTCUSDT", "ETHUSDT"]:
        snap = _symbol_snapshot(snapshot, symbol)
        dec = _symbol_decision(decision, symbol)
        if not snap or not dec:
            lines.extend([f"{symbol}: missing", ""])
            continue
        tf = snap.get("timeframes", {})
        lines.extend(
            [
                f"{symbol}",
                f"价格：{_fmt(snap.get('price', {}).get('last'))}",
                f"15m/1h/4h：{_fmt(tf.get('15m', {}).get('structure'))} / {_fmt(tf.get('1h', {}).get('structure'))} / {_fmt(tf.get('4h', {}).get('structure'))}",
                f"一致性：{_fmt(dec.get('three_period_consistency'))}",
                f"action：{_fmt(dec.get('suggested_action'))}",
                f"risk_level：{_fmt(dec.get('risk_level'))}",
                f"allow_trade：{_fmt(dec.get('allow_trade'))}",
                "",
            ]
        )
    return "\n".join(lines).strip()


def build_symbol_detail(symbol: str) -> str:
    snapshot, decision = _load_reports()
    if not snapshot or not decision:
        return MISSING_REPORT_TEXT

    snap = _symbol_snapshot(snapshot, symbol)
    dec = _symbol_decision(decision, symbol)
    if not snap or not dec:
        return f"{symbol} 报告缺失，请先运行 python main.py --once"

    price = snap.get("price", {})
    derivatives = snap.get("derivatives", {})
    tf = snap.get("timeframes", {})
    reasons = dec.get("reason", [])
    reason_text = "\n".join(f"- {item}" for item in reasons[:25]) if reasons else "- none"
    if len(reasons) > 25:
        reason_text += f"\n- ... 还有 {len(reasons) - 25} 条"

    return "\n".join(
        [
            f"{symbol} 三周期详细报告",
            "",
            f"当前价格：{_fmt(price.get('last'))}",
            f"24h涨跌幅：{_fmt(price.get('change_24h_pct'))}%",
            f"15m结构：{_fmt(tf.get('15m', {}).get('structure'))}",
            f"1h结构：{_fmt(tf.get('1h', {}).get('structure'))}",
            f"4h结构：{_fmt(tf.get('4h', {}).get('structure'))}",
            f"资金费率：{_fmt(derivatives.get('funding_rate'))}",
            f"OI：{_fmt(derivatives.get('open_interest'))}",
            f"多空比：{_fmt(derivatives.get('long_short_ratio'))}",
            f"action：{_fmt(dec.get('suggested_action'))}",
            f"risk_level：{_fmt(dec.get('risk_level'))}",
            "",
            "reason[]：",
            reason_text,
        ]
    )


def build_decision_summary() -> str:
    text = _read_text(OUTPUT_DIR / "market_decision.md")
    if not text:
        return MISSING_REPORT_TEXT
    max_len = 3500
    if len(text) <= max_len:
        return text
    return text[:max_len].rstrip() + "\n\n内容较长，已截断。完整文件见 /files。"


def build_files_text() -> str:
    files = [
        "market_snapshot.json",
        "market_report.md",
        "signal_summary.csv",
        "market_decision.json",
        "market_decision.md",
        "signal_history.csv",
        "performance_report.md",
        "signal_statistics.json",
    ]
    lines = ["当前报告文件路径：", ""]
    for name in files:
        path = OUTPUT_DIR / name
        status = "存在" if path.exists() else "missing"
        lines.append(f"{status}：{path}")
    return "\n".join(lines)


async def market_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(build_market_summary())


async def btc_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(build_symbol_detail("BTCUSDT"))


async def eth_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(build_symbol_detail("ETHUSDT"))


async def decision_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(build_decision_summary())


async def files_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(build_files_text())


async def health_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(format_health_text(read_status()))


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "BTC/ETH 市场雷达只读查询机器人\n\n"
        "可用命令：\n"
        "/market - BTC/ETH 简版总览\n"
        "/btc - BTCUSDT 详细报告\n"
        "/eth - ETHUSDT 详细报告\n"
        "/decision - 当前决策摘要\n"
        "/files - 报告文件路径\n"
        "/health - Collector 健康状态\n\n"
        "本机器人只读报告，不采集数据，不连接交易所下单。"
    )


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("缺少 TELEGRAM_BOT_TOKEN，请在 .env 中配置后再运行。")
        return
    if Application is None:
        print("缺少 python-telegram-bot 依赖，请先运行 pip install -r requirements.txt")
        return

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("market", market_command))
    app.add_handler(CommandHandler("btc", btc_command))
    app.add_handler(CommandHandler("eth", eth_command))
    app.add_handler(CommandHandler("decision", decision_command))
    app.add_handler(CommandHandler("files", files_command))
    app.add_handler(CommandHandler("health", health_command))

    print("BTC/ETH 市场雷达只读查询机器人已启动。")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
