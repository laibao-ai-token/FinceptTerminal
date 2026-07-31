# trade_mcp — Fincept headless MCP servers (OpenCode)

Scheme B: domain-split MCP servers for the asset agent.

| Server | Module | Role |
|--------|--------|------|
| **market** | `trade_mcp.market_server` | Quotes, history, company, yfinance news |
| **paper** | `trade_mcp.paper_server` | Paper trading only |
| **research** | `trade_mcp.research_server` | Backtest, indicators, quantstats, signals→paper bridge |
| **fundamentals** | `trade_mcp.fundamentals_server` | SEC Edgar, FX (Frankfurter), GNews |
| **macro** | `trade_mcp.macro_server` | FRED (+ key), World Bank free |
| **china** | `trade_mcp.china_server` | akshare limited (A/HK/index/news) |

## Run (stdio)

```bash
export PYTHONPATH=/root/workspace/FinceptTerminal
/root/workspace/FinceptTerminal/.venv-pt/bin/python -m trade_mcp.market_server
```

## OpenCode registration

Add to the `mcp` section of `~/.config/opencode/opencode.json` (or project
`.opencode/opencode.json`). Example:

```jsonc
{
  "mcp": {
    "market": { "type": "local", "command": ["/root/workspace/FinceptTerminal/.venv-pt/bin/python", "-m", "trade_mcp.market_server"], "environment": { "PYTHONPATH": "/root/workspace/FinceptTerminal" } },
    "paper": { "type": "local", "command": ["/root/workspace/FinceptTerminal/.venv-pt/bin/python", "-m", "trade_mcp.paper_server"], "environment": { "PYTHONPATH": "/root/workspace/FinceptTerminal" } },
    "research": { "type": "local", "command": ["/root/workspace/FinceptTerminal/.venv-pt/bin/python", "-m", "trade_mcp.research_server"], "environment": { "PYTHONPATH": "/root/workspace/FinceptTerminal" } },
    "fundamentals": { "type": "local", "command": ["/root/workspace/FinceptTerminal/.venv-pt/bin/python", "-m", "trade_mcp.fundamentals_server"], "environment": { "PYTHONPATH": "/root/workspace/FinceptTerminal" } },
    "macro": { "type": "local", "command": ["/root/workspace/FinceptTerminal/.venv-pt/bin/python", "-m", "trade_mcp.macro_server"], "environment": { "PYTHONPATH": "/root/workspace/FinceptTerminal" } },
    "china": { "type": "local", "command": ["/root/workspace/FinceptTerminal/.venv-pt/bin/python", "-m", "trade_mcp.china_server"], "environment": { "PYTHONPATH": "/root/workspace/FinceptTerminal" } }
  }
}
```

## Notes

- Import official `mcp` **before** adding `fincept-qt/scripts` to `sys.path`.
- Paper only; no live brokerage.
- FRED needs `FRED_API_KEY`; World Bank / akshare do not.
- EastMoney (`push2his.eastmoney.com`) is unreachable from this host; HK/A-share/index
  history falls back to yfinance (`.HK` / `.SS` / `.SZ` suffixes).
