#!/usr/bin/env python3
"""MCP server: fincept — single-process aggregation of all 6 sub-servers.

Aggregates every tool registered on the individual FastMCP instances
(market/paper/research/fundamentals/macro/china) into one FastMCP("fincept")
instance. Tool names, parameters and return values are unchanged.
"""
from __future__ import annotations

import inspect

from mcp.server.fastmcp import FastMCP

from trade_mcp.common import ensure_script_paths

ensure_script_paths()

# Import the 6 server modules; each registers its own FastMCP instance.
import trade_mcp.market_server as _market
import trade_mcp.paper_server as _paper
import trade_mcp.research_server as _research
import trade_mcp.fundamentals_server as _fundamentals
import trade_mcp.macro_server as _macro
import trade_mcp.china_server as _china

_SUB_SERVERS = {
    "market": _market,
    "paper": _paper,
    "research": _research,
    "fundamentals": _fundamentals,
    "macro": _macro,
    "china": _china,
}

mcp = FastMCP("fincept")


def _registered_tools(module) -> list:
    """Extract registered tools from a server module's FastMCP instance."""
    inst = getattr(module, "mcp", None)
    if inst is not None:
        try:
            tm = getattr(inst, "_tool_manager", None)
            if tm is not None and hasattr(tm, "list_tools"):
                tools = tm.list_tools()
                if tools:
                    return tools
        except Exception:
            pass
    # Fallback: module-level functions that were registered via @mcp.tool()
    tools = []
    if inst is not None:
        try:
            names = {t.name for t in inst._tool_manager.list_tools()}
        except Exception:
            names = set()
    else:
        names = set()
    for _, fn in inspect.getmembers(module, inspect.isfunction):
        if fn.__module__ == module.__name__ and (not names or fn.__name__ in names):
            tools.append(fn)
    return tools


def _register_tools(module) -> int:
    """Re-register all tools of one sub-server on the aggregated instance."""
    count = 0
    for tool in _registered_tools(module):
        if isinstance(tool, type) or not hasattr(tool, "name"):
            # fallback plain function
            fn = tool
            name = getattr(fn, "__name__", str(fn))
            title = None
            description = fn.__doc__ or ""
        else:
            fn = tool.fn
            name = tool.name
            title = tool.title
            description = tool.description
        mcp.tool(name=name, title=title, description=description)(fn)
        count += 1
    return count


def tool_counts() -> dict:
    """Per-server tool counts (source modules vs aggregated instance)."""
    agg = {t.name for t in mcp._tool_manager.list_tools()}
    counts = {}
    for name, mod in _SUB_SERVERS.items():
        src = {t.name for t in mod.mcp._tool_manager.list_tools()}
        counts[name] = {"source": len(src), "registered": len(src & agg)}
    counts["total"] = len(agg)
    return counts


for _name, _mod in _SUB_SERVERS.items():
    _register_tools(_mod)

if __name__ == "__main__":
    mcp.run(transport="stdio")
