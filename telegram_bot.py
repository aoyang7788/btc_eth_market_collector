from __future__ import annotations

import argparse
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
from telegram_notifier import send_test_message, translate_text, translate_value  # noqa: E402


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
        return "缺失"
    return translate_value(value)


def _cn_action(value: Any) -> str:
    return {
        "LOOK_FOR_LONG": "允许做多",
        "LOOK_FOR_SHORT": "允许做空",
        "ALLOW_LONG": "允许做多",
        "ALLOW_SHORT": "允许做空",
        "WAIT": "观望等待",
        "NO_TRADE": "不交易",
    }.get(str(value), translate_value(value))


def _cn_risk(value: Any) -> str:
    return {
        "LOW": "低风险",
        "MEDIUM": "中风险",
        "HIGH": "高风险",
    }.get(str(value), translate_value(value))


def _cn_trend(value: Any) -> str:
    return {
        "bullish": "多头",
        "bearish": "空头",
        "neutral": "中性",
        "missing": "缺失",
    }.get(str(value), translate_value(value))


def _cn_consistency(value: Any) -> str:
    return {
        "bullish_aligned": "多周期多头共振",
        "bearish_aligned": "多周期空头共振",
        "bullish_pullback": "多头回调结构",
        "bearish_pullback": "空头反弹结构",
        "mixed_neutral": "多周期中性混合",
        "conflict": "多周期冲突",
        "missing": "缺失",
    }.get(str(value), translate_value(value))


def _load_reports() -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    snapshot = _read_json(OUTPUT_DIR / "market_snapshot.json")
    decision = _read_json(OUTPUT_DIR / "market_decision.json")
    return snapshot, decision


def _symbol_snapshot(snapshot: dict[str, Any] | None, symbol: str) -> dict[str, Any] | None:
    return (snapshot or {}).get("symbols", {}).get(symbol)


def _symbol_decision(decision: dict[str, Any] | None, symbol: str) -> dict[str, Any] | None:
    return (decision or {}).get("symbols", {}).get(symbol)


def _latest_plan(symbol: str) -> dict[str, Any]:
    path = OUTPUT_DIR / "signal_history.csv"
    try:
        import csv

        with path.open("r", newline="", encoding="utf-8-sig") as f:
            rows = [row for row in csv.DictReader(f) if row.get("symbol") == symbol]
        if rows:
            return rows[-1]
    except OSError:
        pass
    return {}


def _fmt_price(value: Any) -> str:
    try:
        if value in {"", None}:
            return "暂无"
        number = float(value)
        return f"{number:.2f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return "暂无"


def _bollinger_position(price: Any, bollinger: dict[str, Any]) -> str:
    try:
        if not isinstance(bollinger, dict):
            return "缺失"
        value = float(price)
        upper = float(bollinger.get("upper"))
        middle = float(bollinger.get("middle"))
        lower = float(bollinger.get("lower"))
    except (TypeError, ValueError):
        return "缺失"
    if value > upper:
        return "上轨上方"
    if value < lower:
        return "下轨下方"
    if value >= middle:
        return "中轨上方"
    return "中轨下方"


def _eth_observation_lines(snap: dict[str, Any], dec: dict[str, Any]) -> list[str]:
    price = snap.get("price", {})
    derivatives = snap.get("derivatives", {})
    tf = snap.get("timeframes", {})
    tf4h = tf.get("4h", {})
    structures = dec.get("structures", {})
    return [
        "ETH 当前仅观察，不参与交易统计。",
        f"当前价格：{_fmt(price.get('last'))}",
        f"EMA5：{_fmt(tf4h.get('ema5'))}",
        f"EMA13：{_fmt(tf4h.get('ema13'))}",
        f"布林带位置：{_bollinger_position(price.get('last'), tf4h.get('bollinger', {}))}",
        f"资金费率：{_fmt(derivatives.get('funding_rate'))}",
        f"多空比：{_fmt(derivatives.get('long_short_ratio'))}",
        f"OI：{_fmt(derivatives.get('open_interest'))}",
        f"周期结构：15m {_cn_trend(structures.get('15m'))} / 1h {_cn_trend(structures.get('1h'))} / 4h {_cn_trend(structures.get('4h'))}",
        f"多周期结构：{_cn_consistency(dec.get('three_period_consistency'))}",
    ]


def _plan_lines(symbol: str, current_price: Any, decision_item: dict[str, Any]) -> list[str]:
    plan = _latest_plan(symbol)
    stop_loss = _fmt_price(plan.get("stop_loss"))
    take_profit = _fmt_price(plan.get("take_profit"))
    rr = plan.get("risk_reward") or ""
    rr_text = f"1:{rr}" if rr not in {"", None} else "暂无"
    has_plan = stop_loss != "暂无" and take_profit != "暂无" and rr_text != "暂无"
    lines = [
        "交易计划：",
        f"建议方向：{_cn_action(decision_item.get('suggested_action'))}",
        f"参考入场：{_fmt_price(plan.get('entry_price') or current_price)}",
        f"止损价：{stop_loss}",
        f"止盈价：{take_profit}",
        f"盈亏比：{rr_text}",
        "单笔风险：1R",
        f"允许执行：{'是' if decision_item.get('allow_trade') and has_plan else '否'}",
    ]
    if not has_plan:
        lines.extend(["原因：当前结构不足，暂不生成完整交易计划。"])
    return lines


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
        if symbol == "ETHUSDT":
            lines.extend([symbol, *_eth_observation_lines(snap, dec), ""])
            continue
        lines.extend(
            [
                f"{symbol}",
                f"价格：{_fmt(snap.get('price', {}).get('last'))}",
                f"15m/1h/4h：{_cn_trend(tf.get('15m', {}).get('structure'))} / {_cn_trend(tf.get('1h', {}).get('structure'))} / {_cn_trend(tf.get('4h', {}).get('structure'))}",
                f"一致性：{_cn_consistency(dec.get('three_period_consistency'))}",
                f"建议：{_cn_action(dec.get('suggested_action'))}",
                f"风险等级：{_cn_risk(dec.get('risk_level'))}",
                f"允许交易：{'是' if dec.get('allow_trade') else '否'}",
                *_plan_lines(symbol, snap.get('price', {}).get('last'), dec),
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

    if symbol == "ETHUSDT":
        return "\n".join([f"{symbol} 观察报告", "", *_eth_observation_lines(snap, dec)])

    price = snap.get("price", {})
    derivatives = snap.get("derivatives", {})
    tf = snap.get("timeframes", {})
    reasons = dec.get("reason", [])
    reason_text = "\n".join(f"- {translate_text(item)}" for item in reasons[:25]) if reasons else "- 无"
    if len(reasons) > 25:
        reason_text += f"\n- ... 还有 {len(reasons) - 25} 条"

    return "\n".join(
        [
            f"{symbol} 三周期详细报告",
            "",
            f"当前价格：{_fmt(price.get('last'))}",
            f"24h涨跌幅：{_fmt(price.get('change_24h_pct'))}%",
            f"15m结构：{_cn_trend(tf.get('15m', {}).get('structure'))}",
            f"1h结构：{_cn_trend(tf.get('1h', {}).get('structure'))}",
            f"4h结构：{_cn_trend(tf.get('4h', {}).get('structure'))}",
            f"资金费率：{_fmt(derivatives.get('funding_rate'))}",
            f"OI：{_fmt(derivatives.get('open_interest'))}",
            f"多空比：{_fmt(derivatives.get('long_short_ratio'))}",
            f"建议：{_cn_action(dec.get('suggested_action'))}",
            f"风险等级：{_cn_risk(dec.get('risk_level'))}",
            "",
            *_plan_lines(symbol, price.get('last'), dec),
            "",
            "原因：",
            reason_text,
        ]
    )


def build_decision_summary() -> str:
    text = _read_text(OUTPUT_DIR / "market_decision.md")
    if not text:
        return MISSING_REPORT_TEXT
    text = translate_text(text)
    snapshot, decision = _load_reports()
    if snapshot and decision:
        plan_lines = ["", "## 交易计划", ""]
        for symbol in ["BTCUSDT"]:
            snap = _symbol_snapshot(snapshot, symbol)
            dec = _symbol_decision(decision, symbol)
            if not snap or not dec:
                continue
            plan_lines.extend(
                [
                    f"### {symbol}",
                    "",
                    *_plan_lines(symbol, snap.get("price", {}).get("last"), dec),
                    "",
                ]
            )
        text = text.rstrip() + "\n" + "\n".join(plan_lines).strip()
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


def build_stats_text() -> str:
    stats = _read_json(OUTPUT_DIR / "signal_statistics.json")
    if not stats:
        return "统计报告尚未生成，请先运行 python main.py --once"

    recent = stats.get("recent_10", {})

    def pct(value: Any) -> str:
        return "等待样本" if value is None else f"{value}%"

    def val(value: Any) -> str:
        return "等待样本" if value is None else str(value)

    return "\n".join(
        [
            "BTC 信号统计",
            "",
            f"总信号：{stats.get('total_signals', 0)}",
            "",
            f"总交易：{stats.get('total_trades', 0)}",
            f"胜率：{pct(stats.get('win_rate'))}",
            f"平均盈亏比：{val(stats.get('average_rr'))}",
            f"EV：{val(stats.get('ev'))}",
            f"Profit Factor：{val(stats.get('profit_factor'))}",
            f"最大连赢：{stats.get('max_win_streak', 0)}",
            f"最大连亏：{stats.get('max_loss_streak', 0)}",
            "",
            f"最近10次：{' '.join(translate_value(item) for item in recent.get('results', [])) or '暂无已完成交易'}",
        ]
    )


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


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(build_stats_text())


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
        "/stats - 信号胜率统计\n\n"
        "本机器人只读报告，不采集数据，不连接交易所下单。"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="BTC/ETH 市场雷达 Telegram 只读机器人")
    parser.add_argument("--test", action="store_true", help="发送 Telegram 推送测试消息后退出")
    args = parser.parse_args()

    if args.test:
        result = send_test_message()
        if result.get("ok"):
            print("Telegram 测试消息发送成功。")
        else:
            print(f"Telegram 测试消息发送失败：{result.get('error')}")
        return

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
    app.add_handler(CommandHandler("stats", stats_command))

    print("BTC/ETH 市场雷达只读查询机器人已启动。")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
