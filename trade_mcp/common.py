"""Shared helpers for Fincept headless MCP servers."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# Official MCP package must load before scripts/ (local scripts/mcp package shadows it)
from mcp.server.fastmcp import FastMCP  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "fincept-qt" / "scripts"
BT_DIR = SCRIPTS / "Analytics" / "backtesting" / "bt"
BT_PARENT = SCRIPTS / "Analytics" / "backtesting"
PY = str(ROOT / ".venv-pt" / "bin" / "python")


def ensure_script_paths() -> None:
    for p in (str(SCRIPTS), str(BT_DIR), str(BT_PARENT)):
        if p not in sys.path:
            sys.path.insert(0, p)


def ok(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def err(msg: str, **extra: Any) -> str:
    payload = {"error": msg, **extra}
    return json.dumps(payload, ensure_ascii=False, default=str)


def trim_list(data: Any, max_items: int = 60) -> Any:
    if isinstance(data, list) and len(data) > max_items:
        return {"count": len(data), "tail": data[-max_items:]}
    return data
