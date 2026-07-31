#!/usr/bin/env python3
"""Deprecated monolithic entrypoint.

Use domain MCP servers instead (scheme B):
  trade_mcp/market_server.py
  trade_mcp/paper_server.py
  trade_mcp/research_server.py

Registered in ~/.config/opencode/opencode.json as mcp.market / mcp.paper / mcp.research.
This file remains as a short pointer for older docs.
"""
import sys

print(
    "trade_mcp_server.py is deprecated. Use:\n"
    "  python -m trade_mcp.market_server\n"
    "  python -m trade_mcp.paper_server\n"
    "  python -m trade_mcp.research_server\n",
    file=sys.stderr,
)
sys.exit(2)
