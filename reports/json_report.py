from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_json_report(snapshot: dict[str, Any], path: Path) -> None:
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
