from __future__ import annotations

from pathlib import Path
from typing import Any


def fmt(value: Any) -> str:
    if value is None:
        return "missing"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def timeframe_section(name: str, data: dict[str, Any]) -> list[str]:
    boll = data.get("bollinger", {})
    macd = data.get("macd", {})
    vol = data.get("volume_change", {})
    return [
        f"### {name}结构",
        "",
        f"- 状态：{fmt(data.get('structure'))}",
        f"- EMA5 / EMA13：{fmt(data.get('ema5'))} / {fmt(data.get('ema13'))}",
        f"- MACD：macd={fmt(macd.get('macd'))}, signal={fmt(macd.get('signal'))}, histogram={fmt(macd.get('histogram'))}",
        f"- 布林带位置：upper={fmt(boll.get('upper'))}, middle={fmt(boll.get('middle'))}, lower={fmt(boll.get('lower'))}",
        f"- 成交量变化：current={fmt(vol.get('current'))}, avg20={fmt(vol.get('avg20'))}, ratio={fmt(vol.get('ratio'))}",
        "",
    ]


def write_markdown_report(snapshot: dict[str, Any], path: Path) -> None:
    lines = [
        "# BTC/ETH 三周期市场快照",
        "",
        f"生成时间：{snapshot.get('generated_at')}",
        "",
        "数据源：Binance Futures API；清算地图：CoinGlass 预留字段，V1 未接入时标记 missing。",
        "",
    ]

    for symbol, data in snapshot.get("symbols", {}).items():
        price = data.get("price", {})
        derivatives = data.get("derivatives", {})
        daily = data.get("daily_ma", {})
        decision = data.get("decision", {})
        lines.extend(
            [
                f"## {symbol}",
                "",
                "### 当前概览",
                "",
                f"- 当前价格：{fmt(price.get('last'))}",
                f"- 24h涨跌幅：{fmt(price.get('change_24h_pct'))}%",
                f"- 24h高低点：{fmt(price.get('high_24h'))} / {fmt(price.get('low_24h'))}",
                f"- 24h成交量：{fmt(price.get('volume_24h'))}",
                f"- 资金费率：{fmt(derivatives.get('funding_rate'))}",
                f"- 下一次资金费率时间：{fmt(derivatives.get('next_funding_time'))}",
                f"- OI：{fmt(derivatives.get('open_interest'))}",
                f"- OI变化：{fmt(derivatives.get('open_interest_change'))}",
                f"- 多空比：{fmt(derivatives.get('long_short_ratio'))}",
                f"- MA50 / MA200：{fmt(daily.get('ma50'))} / {fmt(daily.get('ma200'))}",
                "",
            ]
        )
        for tf in ["15m", "1h", "4h"]:
            lines.extend(timeframe_section(tf, data.get("timeframes", {}).get(tf, {})))

        liq_map = derivatives.get("liquidation_map", {})
        lines.extend(
            [
                "### 交易状态",
                "",
                f"- 当前是否多头环境：{fmt(decision.get('is_bullish_environment'))}",
                f"- 当前是否空头环境：{fmt(decision.get('is_bearish_environment'))}",
                f"- 是否允许开仓：{fmt(decision.get('allow_open'))}",
                f"- 是否禁止交易：{fmt(decision.get('forbid_trade'))}",
                f"- 原因：{'; '.join(decision.get('reason', [])) or 'none'}",
                "",
                "### 清算区域",
                "",
                "- 上方关键区域：missing",
                "- 下方关键区域：missing",
                f"- 数据状态：{fmt(liq_map.get('status'))}",
                f"- 原因：{fmt(liq_map.get('reason'))}",
                "",
            ]
        )

    path.write_text("\n".join(lines), encoding="utf-8-sig")
