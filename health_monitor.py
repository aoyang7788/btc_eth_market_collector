from __future__ import annotations

import json
import logging
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from config import BASE_DIR, output_dir


LOG_DIR = BASE_DIR / "logs"
HEALTH_DIR = BASE_DIR / "health"
LOG_PATH = LOG_DIR / "collector.log"
STATUS_PATH = HEALTH_DIR / "status.json"

OUTPUT_FILES = {
    "market_snapshot": "market_snapshot.json",
    "market_report": "market_report.md",
    "signal_summary": "signal_summary.csv",
    "market_decision": "market_decision.json",
    "performance_report": "performance_report.md",
}


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def setup_collector_logger() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("market_collector")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not any(isinstance(handler, logging.FileHandler) and Path(handler.baseFilename) == LOG_PATH for handler in logger.handlers):
        handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    return logger


def default_status() -> dict[str, Any]:
    return {
        "status": "warning",
        "last_run_at": "",
        "last_success_at": "",
        "last_error_at": "",
        "last_error_message": "",
        "consecutive_success": 0,
        "consecutive_failures": 0,
        "next_run_at": "",
        "outputs": {key: "missing" for key in OUTPUT_FILES},
    }


def read_status() -> dict[str, Any]:
    try:
        return json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default_status()


def output_statuses() -> dict[str, str]:
    out = output_dir()
    return {key: "ok" if (out / filename).exists() else "missing" for key, filename in OUTPUT_FILES.items()}


def write_status(status: dict[str, Any]) -> None:
    HEALTH_DIR.mkdir(parents=True, exist_ok=True)
    status["outputs"] = output_statuses()
    STATUS_PATH.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")


def record_success(started_at: str, next_run_at: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    status = read_status()
    now = iso_now()
    status.update(
        {
            "status": "ok",
            "last_run_at": started_at,
            "last_success_at": now,
            "last_error_message": status.get("last_error_message", ""),
            "consecutive_success": int(status.get("consecutive_success") or 0) + 1,
            "consecutive_failures": 0,
            "next_run_at": next_run_at,
        }
    )
    if details:
        status["last_run_details"] = details
    write_status(status)
    return status


def record_failure(started_at: str, error: BaseException, next_run_at: str) -> dict[str, Any]:
    status = read_status()
    now = iso_now()
    status.update(
        {
            "status": "error",
            "last_run_at": started_at,
            "last_error_at": now,
            "last_error_message": f"{type(error).__name__}: {error}",
            "consecutive_success": 0,
            "consecutive_failures": int(status.get("consecutive_failures") or 0) + 1,
            "next_run_at": next_run_at,
        }
    )
    status["last_traceback"] = traceback.format_exc(limit=8)
    write_status(status)
    return status


def next_run_iso(interval_minutes: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=max(interval_minutes, 1))).isoformat()


def format_health_text(status: dict[str, Any] | None = None) -> str:
    data = status or read_status()
    outputs = data.get("outputs", {})
    outputs_text = "\n".join(f"- {key}: {value}" for key, value in outputs.items()) or "- none"
    last_error = data.get("last_error_message") or "无"
    return "\n".join(
        [
            f"状态：{data.get('status', 'warning')}",
            f"最后运行：{data.get('last_run_at', '') or '无'}",
            f"最后成功运行：{data.get('last_success_at', '') or '无'}",
            f"连续成功：{data.get('consecutive_success', 0)}",
            f"连续失败：{data.get('consecutive_failures', 0)}",
            f"最近错误：{last_error}",
            f"下一次运行：{data.get('next_run_at', '') or '无'}",
            "输出文件：",
            outputs_text,
        ]
    )
