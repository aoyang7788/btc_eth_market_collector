from __future__ import annotations

from typing import Any

import requests

from config import BINANCE_FUTURES_BASE_URL, REQUEST_TIMEOUT_SECONDS


class BinanceFuturesClient:
    def __init__(self, base_url: str = BINANCE_FUTURES_BASE_URL, timeout: int = REQUEST_TIMEOUT_SECONDS):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            response = requests.get(url, params=params or {}, timeout=self.timeout)
            response.raise_for_status()
            return {"ok": True, "data": response.json(), "error": None}
        except requests.RequestException as exc:
            return {"ok": False, "data": None, "error": f"{type(exc).__name__}: request failed"}
        except ValueError:
            return {"ok": False, "data": None, "error": "invalid json response"}

    def get_klines(self, symbol: str, interval: str, limit: int = 300) -> dict[str, Any]:
        return self._get("/fapi/v1/klines", {"symbol": symbol, "interval": interval, "limit": limit})

    def get_ticker_24h(self, symbol: str) -> dict[str, Any]:
        return self._get("/fapi/v1/ticker/24hr", {"symbol": symbol})

    def get_premium_index(self, symbol: str) -> dict[str, Any]:
        return self._get("/fapi/v1/premiumIndex", {"symbol": symbol})

    def get_open_interest(self, symbol: str) -> dict[str, Any]:
        return self._get("/fapi/v1/openInterest", {"symbol": symbol})

    def get_open_interest_hist(self, symbol: str, period: str = "15m", limit: int = 30) -> dict[str, Any]:
        return self._get("/futures/data/openInterestHist", {"symbol": symbol, "period": period, "limit": limit})

    def get_long_short_ratio(self, symbol: str, period: str = "15m", limit: int = 30) -> dict[str, Any]:
        return self._get(
            "/futures/data/globalLongShortAccountRatio",
            {"symbol": symbol, "period": period, "limit": limit},
        )
