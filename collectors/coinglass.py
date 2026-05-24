from __future__ import annotations

from typing import Any

from config import COINGLASS_API_KEY


def get_liquidation_map_placeholder() -> dict[str, Any]:
    reason = "COINGLASS_API_KEY not configured" if not COINGLASS_API_KEY else "not implemented in V1"
    return {
        "status": "missing",
        "source": "coinglass",
        "reason": reason,
        "key_zones": [],
    }
