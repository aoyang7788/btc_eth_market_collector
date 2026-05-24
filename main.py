from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from collectors.binance_futures import BinanceFuturesClient
from collectors.coinglass import get_liquidation_map_placeholder
from config import RUN_INTERVAL_MINUTES, SYMBOLS, output_dir
from decision_engine import build_market_decision
from health_monitor import (
    format_health_text,
    next_run_iso,
    record_failure,
    record_success,
    setup_collector_logger,
)
from indicators.regimes import judge_decision
from indicators.technicals import daily_ma, parse_klines, round_value, safe_float, timeframe_snapshot
from reports.csv_report import write_signal_summary
from reports.decision_report import write_decision_json, write_decision_markdown
from reports.json_report import write_json_report
from reports.markdown_report import write_markdown_report
from reports.performance_report import write_performance_report
from signal_tracker import build_signal_statistics, update_signal_history, write_statistics_json


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def iso_from_ms(value: Any) -> str:
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return ""


def null_timeframe() -> dict[str, Any]:
    return {
        "structure": "missing",
        "ema5": None,
        "ema13": None,
        "bollinger": {"upper": None, "middle": None, "lower": None},
        "macd": {"macd": None, "signal": None, "histogram": None},
        "volume_change": {"current": None, "avg20": None, "ratio": None},
    }


def source_status_template() -> dict[str, str]:
    return {
        "binance_klines": "missing",
        "binance_funding": "missing",
        "binance_oi": "missing",
        "binance_long_short_ratio": "missing",
        "coinglass_liquidation_map": "missing",
    }


def get_price_block(ticker: dict[str, Any] | None) -> dict[str, float | None]:
    if not ticker:
        return {"last": None, "change_24h_pct": None, "high_24h": None, "low_24h": None, "volume_24h": None}
    return {
        "last": round_value(safe_float(ticker.get("lastPrice"))),
        "change_24h_pct": round_value(safe_float(ticker.get("priceChangePercent"))),
        "high_24h": round_value(safe_float(ticker.get("highPrice"))),
        "low_24h": round_value(safe_float(ticker.get("lowPrice"))),
        "volume_24h": round_value(safe_float(ticker.get("volume"))),
    }


def oi_change_from_hist(hist: list[dict[str, Any]] | None) -> float | None:
    if not hist or len(hist) < 2:
        return None
    first = safe_float(hist[0].get("sumOpenInterest"))
    last = safe_float(hist[-1].get("sumOpenInterest"))
    if first is None or last is None or first == 0:
        return None
    return round_value((last - first) / first * 100)


def long_short_latest(rows: list[dict[str, Any]] | None) -> float | None:
    if not rows:
        return None
    return round_value(safe_float(rows[-1].get("longShortRatio")))


def collect_symbol(client: BinanceFuturesClient, symbol: str) -> dict[str, Any]:
    status = source_status_template()

    tf_klines: dict[str, list[dict[str, float | int]] | None] = {}
    all_kline_ok = True
    for interval in ["15m", "1h", "4h"]:
        result = client.get_klines(symbol, interval, 300)
        if result["ok"] and isinstance(result["data"], list):
            tf_klines[interval] = parse_klines(result["data"])
        else:
            tf_klines[interval] = None
            all_kline_ok = False
    daily_result = client.get_klines(symbol, "1d", 250)
    daily_klines = parse_klines(daily_result["data"]) if daily_result["ok"] and isinstance(daily_result["data"], list) else None
    if not daily_klines:
        all_kline_ok = False
    if all_kline_ok:
        status["binance_klines"] = "ok"

    ticker_result = client.get_ticker_24h(symbol)
    ticker = ticker_result["data"] if ticker_result["ok"] and isinstance(ticker_result["data"], dict) else None

    funding_result = client.get_premium_index(symbol)
    funding = funding_result["data"] if funding_result["ok"] and isinstance(funding_result["data"], dict) else None
    if funding:
        status["binance_funding"] = "ok"

    oi_result = client.get_open_interest(symbol)
    oi = oi_result["data"] if oi_result["ok"] and isinstance(oi_result["data"], dict) else None
    oi_hist_result = client.get_open_interest_hist(symbol)
    oi_hist = oi_hist_result["data"] if oi_hist_result["ok"] and isinstance(oi_hist_result["data"], list) else None
    if oi:
        status["binance_oi"] = "ok"

    ratio_result = client.get_long_short_ratio(symbol)
    ratio_rows = ratio_result["data"] if ratio_result["ok"] and isinstance(ratio_result["data"], list) else None
    if ratio_rows:
        status["binance_long_short_ratio"] = "ok"

    timeframes = {tf: timeframe_snapshot(tf_klines.get(tf)) if tf_klines.get(tf) else null_timeframe() for tf in ["15m", "1h", "4h"]}
    liquidation_map = get_liquidation_map_placeholder()

    derivatives = {
        "funding_rate": round_value(safe_float(funding.get("lastFundingRate")) if funding else None, 8),
        "next_funding_time": iso_from_ms(funding.get("nextFundingTime")) if funding else "",
        "open_interest": round_value(safe_float(oi.get("openInterest")) if oi else None),
        "open_interest_change": oi_change_from_hist(oi_hist),
        "long_short_ratio": long_short_latest(ratio_rows),
        "liquidations": {"long_liq_24h": "missing", "short_liq_24h": "missing"},
        "liquidation_map": liquidation_map,
    }

    return {
        "source_status": status,
        "price": get_price_block(ticker),
        "timeframes": timeframes,
        "daily_ma": daily_ma(daily_klines),
        "derivatives": derivatives,
        "decision": judge_decision(status, timeframes),
    }


def collect_market_snapshot() -> dict[str, Any]:
    client = BinanceFuturesClient()
    return {
        "generated_at": iso_now(),
        "symbols": {symbol: collect_symbol(client, symbol) for symbol in SYMBOLS},
    }


def write_outputs(snapshot: dict[str, Any], out_dir: Path | None = None) -> dict[str, str]:
    out = out_dir or output_dir()
    json_path = out / "market_snapshot.json"
    markdown_path = out / "market_report.md"
    csv_path = out / "signal_summary.csv"
    decision_json_path = out / "market_decision.json"
    decision_markdown_path = out / "market_decision.md"
    signal_history_path = out / "signal_history.csv"
    performance_report_path = out / "performance_report.md"
    signal_statistics_path = out / "signal_statistics.json"
    write_json_report(snapshot, json_path)
    write_markdown_report(snapshot, markdown_path)
    write_signal_summary(snapshot, csv_path)
    decision = build_market_decision(snapshot)
    write_decision_json(decision, decision_json_path)
    write_decision_markdown(decision, decision_markdown_path)
    history_rows = update_signal_history(snapshot, decision, signal_history_path)
    signal_stats = build_signal_statistics(history_rows)
    write_statistics_json(signal_stats, signal_statistics_path)
    write_performance_report(signal_stats, performance_report_path)
    return {
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
        "csv_path": str(csv_path),
        "decision_json_path": str(decision_json_path),
        "decision_markdown_path": str(decision_markdown_path),
        "signal_history_path": str(signal_history_path),
        "performance_report_path": str(performance_report_path),
        "signal_statistics_path": str(signal_statistics_path),
    }


def write_decision_outputs_from_snapshot(snapshot: dict[str, Any], out_dir: Path | None = None) -> dict[str, str]:
    out = out_dir or output_dir()
    decision_json_path = out / "market_decision.json"
    decision_markdown_path = out / "market_decision.md"
    signal_history_path = out / "signal_history.csv"
    performance_report_path = out / "performance_report.md"
    signal_statistics_path = out / "signal_statistics.json"
    decision = build_market_decision(snapshot)
    write_decision_json(decision, decision_json_path)
    write_decision_markdown(decision, decision_markdown_path)
    history_rows = update_signal_history(snapshot, decision, signal_history_path)
    signal_stats = build_signal_statistics(history_rows)
    write_statistics_json(signal_stats, signal_statistics_path)
    write_performance_report(signal_stats, performance_report_path)
    return {
        "decision_json_path": str(decision_json_path),
        "decision_markdown_path": str(decision_markdown_path),
        "signal_history_path": str(signal_history_path),
        "performance_report_path": str(performance_report_path),
        "signal_statistics_path": str(signal_statistics_path),
    }


def run_decision_only() -> dict[str, str]:
    snapshot_path = output_dir() / "market_snapshot.json"
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    return write_decision_outputs_from_snapshot(snapshot)


def get_latest_market_report() -> dict[str, str]:
    out = output_dir()
    json_path = out / "market_snapshot.json"
    markdown_path = out / "market_report.md"
    csv_path = out / "signal_summary.csv"
    decision_json_path = out / "market_decision.json"
    decision_markdown_path = out / "market_decision.md"
    summary_text = "market report not generated"
    try:
        import json

        snapshot = json.loads(json_path.read_text(encoding="utf-8"))
        parts = []
        for symbol, data in snapshot.get("symbols", {}).items():
            tf = data.get("timeframes", {})
            parts.append(
                f"{symbol.replace('USDT', '')}: 4h {tf.get('4h', {}).get('structure')}, "
                f"1h {tf.get('1h', {}).get('structure')}, "
                f"15m {tf.get('15m', {}).get('structure')}, "
                f"allow_open={str(data.get('decision', {}).get('allow_open')).lower()}"
            )
        summary_text = " | ".join(parts) if parts else summary_text
    except (FileNotFoundError, ValueError, OSError):
        pass
    return {
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
        "csv_path": str(csv_path),
        "decision_json_path": str(decision_json_path),
        "decision_markdown_path": str(decision_markdown_path),
        "summary_text": summary_text,
    }


def get_latest_market_decision() -> dict[str, str]:
    out = output_dir()
    decision_json_path = out / "market_decision.json"
    decision_markdown_path = out / "market_decision.md"
    summary_text = "market decision not generated"
    try:
        import json

        decision = json.loads(decision_json_path.read_text(encoding="utf-8"))
        parts = []
        for symbol, data in decision.get("symbols", {}).items():
            parts.append(
                f"{symbol}: action={data.get('suggested_action')}, "
                f"risk={data.get('risk_level')}, "
                f"consistency={data.get('three_period_consistency')}"
            )
        summary_text = " | ".join(parts) if parts else summary_text
    except (FileNotFoundError, ValueError, OSError):
        pass
    return {
        "json_path": str(decision_json_path),
        "markdown_path": str(decision_markdown_path),
        "summary_text": summary_text,
    }


def run_once() -> dict[str, str]:
    snapshot = collect_market_snapshot()
    return write_outputs(snapshot)


def run_once_monitored(interval_minutes: int = RUN_INTERVAL_MINUTES) -> dict[str, str]:
    logger = setup_collector_logger()
    started_at = iso_now()
    logger.info("ROUND_START started_at=%s", started_at)
    try:
        paths = run_once()
        ended_at = iso_now()
        snapshot_data = json.loads(Path(paths["json_path"]).read_text(encoding="utf-8"))
        btc_status = snapshot_data.get("symbols", {}).get("BTCUSDT", {}).get("source_status", {})
        eth_status = snapshot_data.get("symbols", {}).get("ETHUSDT", {}).get("source_status", {})
        btc_data_status = "ok" if btc_status.get("binance_klines") == "ok" else "missing"
        eth_data_status = "ok" if eth_status.get("binance_klines") == "ok" else "missing"
        next_run_at = next_run_iso(interval_minutes)
        details = {
            "round_started_at": started_at,
            "round_ended_at": ended_at,
            "btc_data": btc_data_status,
            "eth_data": eth_data_status,
            "decision_files": "ok"
            if Path(paths["decision_json_path"]).exists() and Path(paths["decision_markdown_path"]).exists()
            else "missing",
            "signal_tracking": "ok" if Path(paths["signal_history_path"]).exists() else "missing",
        }
        record_success(started_at, next_run_at, details)
        logger.info(
            "ROUND_SUCCESS started_at=%s ended_at=%s btc_data=%s eth_data=%s decision_files=%s signal_tracking=%s next_run_at=%s",
            started_at,
            ended_at,
            details["btc_data"],
            details["eth_data"],
            details["decision_files"],
            details["signal_tracking"],
            next_run_at,
        )
        return paths
    except Exception as exc:
        next_run_at = next_run_iso(interval_minutes)
        record_failure(started_at, exc, next_run_at)
        logger.exception("ROUND_ERROR started_at=%s next_run_at=%s error=%s", started_at, next_run_at, exc)
        raise


def main() -> None:
    logger = setup_collector_logger()
    logger.info("COLLECTOR_START")
    parser = argparse.ArgumentParser(description="BTC/ETH 三周期市场数据采集与决策系统 V5")
    parser.add_argument("--once", action="store_true", help="立即采集一次并生成报告")
    parser.add_argument("--loop", action="store_true", help="循环运行")
    parser.add_argument("--decision-only", action="store_true", help="只读取现有 market_snapshot.json 并生成决策报告")
    parser.add_argument("--health", action="store_true", help="打印健康状态")
    parser.add_argument("--interval", type=int, default=RUN_INTERVAL_MINUTES, help="循环间隔，单位分钟")
    args = parser.parse_args()

    if not args.once and not args.loop and not args.decision_only and not args.health:
        args.once = True

    if args.health:
        print(format_health_text())
        return

    if args.decision_only:
        paths = run_decision_only()
        print(f"generated: {paths['decision_json_path']}")
        print(f"generated: {paths['decision_markdown_path']}")
        print(f"generated: {paths['signal_history_path']}")
        print(f"generated: {paths['performance_report_path']}")
        print(f"generated: {paths['signal_statistics_path']}")

    if args.once:
        paths = run_once_monitored(args.interval)
        print(f"generated: {paths['json_path']}")
        print(f"generated: {paths['markdown_path']}")
        print(f"generated: {paths['csv_path']}")
        print(f"generated: {paths['decision_json_path']}")
        print(f"generated: {paths['decision_markdown_path']}")
        print(f"generated: {paths['signal_history_path']}")
        print(f"generated: {paths['performance_report_path']}")
        print(f"generated: {paths['signal_statistics_path']}")

    if args.loop:
        print(f"{iso_now()} collector loop started, interval={args.interval} minutes")
        logger.info("LOOP_START interval_minutes=%s", args.interval)
        try:
            while True:
                try:
                    paths = run_once_monitored(args.interval)
                    print(f"{iso_now()} generated reports in {Path(paths['json_path']).parent}")
                except Exception as exc:
                    print(f"{iso_now()} round failed: {type(exc).__name__}: {exc}")
                time.sleep(max(args.interval, 1) * 60)
        except KeyboardInterrupt:
            logger.info("LOOP_STOP keyboard_interrupt")
            print("collector loop stopped")


if __name__ == "__main__":
    main()
