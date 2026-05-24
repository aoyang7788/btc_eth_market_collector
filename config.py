import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None


BASE_DIR = Path(__file__).resolve().parent

if load_dotenv:
    load_dotenv(BASE_DIR / ".env")


SYMBOLS = ["BTCUSDT", "ETHUSDT"]
TIMEFRAMES = ["15m", "1h", "4h"]

BINANCE_FUTURES_BASE_URL = os.getenv("BINANCE_FUTURES_BASE_URL", "https://fapi.binance.com").rstrip("/")
COINGLASS_BASE_URL = os.getenv("COINGLASS_BASE_URL", "https://open-api-v4.coinglass.com").rstrip("/")
COINGLASS_API_KEY = os.getenv("COINGLASS_API_KEY", "")
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "outputs"))
RUN_INTERVAL_MINUTES = int(os.getenv("RUN_INTERVAL_MINUTES", "15"))
REQUEST_TIMEOUT_SECONDS = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "10"))


def output_dir() -> Path:
    path = OUTPUT_DIR
    if not path.is_absolute():
        path = BASE_DIR / path
    path.mkdir(parents=True, exist_ok=True)
    return path
