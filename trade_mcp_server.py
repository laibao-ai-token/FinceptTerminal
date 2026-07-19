#!/usr/bin/env python3
"""Trade MCP Server — expose Fincept headless tools to OpenCode.

Tools: market quote/history/news, paper trading, backtest.
Only paper trading; no live brokerage.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent
SCRIPTS = ROOT / "fincept-qt" / "scripts"
BT_DIR = SCRIPTS / "Analytics" / "backtesting" / "bt"
BT_PARENT = SCRIPTS / "Analytics" / "backtesting"

# Import official MCP package BEFORE adding scripts/ (which has a local mcp/ package)
from mcp.server.fastmcp import FastMCP

for p in (str(SCRIPTS), str(BT_DIR), str(BT_PARENT)):
    if p not in sys.path:
        sys.path.insert(0, p)

mcp = FastMCP("trade")


def _ok(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def _err(msg: str, **extra: Any) -> str:
    payload = {"error": msg, **extra}
    return json.dumps(payload, ensure_ascii=False, default=str)


@mcp.tool()
def market_quote(symbol: str) -> str:
    """Get latest market quote for a symbol (e.g. AAPL, 1810.HK, XIACY)."""
    try:
        import yfinance_data as yf_data
        return _ok(yf_data.get_quote(symbol))
    except Exception as e:
        return _err(str(e), symbol=symbol)


@mcp.tool()
def market_history(
    symbol: str,
    period: str = "6mo",
    interval: str = "1d",
) -> str:
    """Get historical OHLCV. period: 1d,5d,1mo,3mo,6mo,1y,2y,5y,max. interval: 1d,1h,1wk."""
    try:
        import yfinance_data as yf_data
        data = yf_data.get_historical_period(symbol, period, interval)
        if isinstance(data, list) and len(data) > 200:
            return _ok({"symbol": symbol, "period": period, "count": len(data), "tail": data[-60:]})
        return _ok(data)
    except Exception as e:
        return _err(str(e), symbol=symbol)


@mcp.tool()
def news_search(query: str, max_results: int = 10) -> str:
    """Search company/market news via yfinance (symbol or company ticker)."""
    try:
        import yfinance_data as yf_data
        items = yf_data.get_news(query, count=max_results)
        return _ok({"query": query, "count": len(items) if isinstance(items, list) else 0, "data": items})
    except Exception as e:
        return _err(str(e), query=query)


def _pt():
    import paper_trading as pt
    pt._init_db_singleton()
    return pt


@mcp.tool()
def paper_create(
    name: str = "agent",
    balance: float = 100000.0,
    fee_rate: float = 0.001,
    currency: str = "USD",
) -> str:
    """Create a paper-trading portfolio. Returns portfolio id and balance."""
    try:
        pt = _pt()
        return _ok(pt.create_portfolio(name, float(balance), currency, 1.0, "cross", float(fee_rate)))
    except Exception as e:
        return _err(str(e))


@mcp.tool()
def paper_list() -> str:
    """List all paper portfolios."""
    try:
        return _ok(_pt().list_portfolios())
    except Exception as e:
        return _err(str(e))


@mcp.tool()
def paper_place_order(
    portfolio_id: str,
    symbol: str,
    side: str,
    quantity: float,
    price: float,
    order_type: str = "market",
    stop_price: Optional[float] = None,
) -> str:
    """Place paper order. side=buy|sell. Market orders need reference price for fill."""
    try:
        pt = _pt()
        return _ok(
            pt.place_order(
                portfolio_id,
                symbol,
                side.lower(),
                order_type.lower(),
                float(quantity),
                float(price) if price is not None else None,
                float(stop_price) if stop_price is not None else None,
            )
        )
    except Exception as e:
        return _err(str(e))


@mcp.tool()
def paper_fill_order(order_id: str, price: float, quantity: Optional[float] = None) -> str:
    """Fill a pending paper order at given price."""
    try:
        pt = _pt()
        qty = float(quantity) if quantity is not None else None
        return _ok(pt.fill_order(order_id, float(price), qty))
    except Exception as e:
        return _err(str(e))


@mcp.tool()
def paper_positions(portfolio_id: str) -> str:
    """List open positions for a portfolio."""
    try:
        return _ok(_pt().get_positions(portfolio_id))
    except Exception as e:
        return _err(str(e))


@mcp.tool()
def paper_stats(portfolio_id: str) -> str:
    """Portfolio stats: balance, pnl, trades, win_rate, fees."""
    try:
        return _ok(_pt().get_stats(portfolio_id))
    except Exception as e:
        return _err(str(e))


@mcp.tool()
def paper_mark(portfolio_id: str, symbol: str, price: float) -> str:
    """Mark symbol price for unrealized PnL / stop checks."""
    try:
        return _ok(_pt().mark_price(portfolio_id, symbol, float(price)))
    except Exception as e:
        return _err(str(e))


@mcp.tool()
def paper_check_stops(portfolio_id: str) -> str:
    """Evaluate SL/TP and stop orders against last marks."""
    try:
        return _ok(_pt().check_stops(portfolio_id))
    except Exception as e:
        return _err(str(e))


@mcp.tool()
def paper_orders(portfolio_id: str, status: str = "") -> str:
    """List orders. Optional status filter: open|filled|cancelled."""
    try:
        return _ok(_pt().get_orders(portfolio_id, status))
    except Exception as e:
        return _err(str(e))


@mcp.tool()
def paper_buy(
    portfolio_id: str,
    symbol: str,
    quantity: float,
    price: Optional[float] = None,
) -> str:
    """Convenience: quote (if price omitted) + market buy + fill in one call."""
    try:
        pt = _pt()
        if price is None:
            import yfinance_data as yf_data
            q = yf_data.get_quote(symbol)
            if isinstance(q, dict) and q.get("error"):
                return _err(q["error"], symbol=symbol)
            price = float(q["price"])
        o = pt.place_order(portfolio_id, symbol, "buy", "market", float(quantity), float(price))
        if "error" in o:
            return _ok(o)
        f = pt.fill_order(o["id"], float(price))
        return _ok({"order": o, "fill": f, "price": price})
    except Exception as e:
        return _err(str(e))


@mcp.tool()
def paper_sell(
    portfolio_id: str,
    symbol: str,
    quantity: float,
    price: Optional[float] = None,
) -> str:
    """Convenience: quote (if price omitted) + market sell + fill in one call."""
    try:
        pt = _pt()
        if price is None:
            import yfinance_data as yf_data
            q = yf_data.get_quote(symbol)
            if isinstance(q, dict) and q.get("error"):
                return _err(q["error"], symbol=symbol)
            price = float(q["price"])
        o = pt.place_order(portfolio_id, symbol, "sell", "market", float(quantity), float(price))
        if "error" in o:
            return _ok(o)
        f = pt.fill_order(o["id"], float(price))
        return _ok({"order": o, "fill": f, "price": price})
    except Exception as e:
        return _err(str(e))


@mcp.tool()
def backtest_run(
    symbol: str,
    strategy: str = "sma_crossover",
    start_date: str = "2024-01-01",
    end_date: str = "2024-12-31",
    initial_capital: float = 100000.0,
) -> str:
    """Run portfolio backtest. strategy examples: equal_weight, sma_crossover, momentum, risk_parity."""
    try:
        from bt_provider import BtProvider

        provider = BtProvider()
        req = {
            "strategy": {"type": strategy, "params": {}},
            "symbols": [symbol],
            "startDate": start_date,
            "endDate": end_date,
            "initialCapital": float(initial_capital),
            "commission": 0.001,
        }
        result = provider.run_backtest(req)
        if isinstance(result, dict):
            for key in ("equityCurve", "equity_curve", "trades", "returns"):
                if key in result and isinstance(result[key], list) and len(result[key]) > 50:
                    result[key] = {"count": len(result[key]), "tail": result[key][-20:]}
        return _ok(result)
    except Exception as e:
        return _err(str(e), symbol=symbol, strategy=strategy)


@mcp.tool()
def backtest_strategies() -> str:
    """List available backtest strategy types."""
    try:
        from bt_provider import BtProvider
        return _ok(BtProvider().get_strategies({}))
    except Exception as e:
        return _err(str(e))


@mcp.tool()
def trade_loop_demo(symbol: str = "AAPL", quantity: float = 10.0) -> str:
    """End-to-end paper demo: create portfolio, buy, mark +1%, sell, return stats."""
    try:
        pt = _pt()
        import yfinance_data as yf_data

        q = yf_data.get_quote(symbol)
        if isinstance(q, dict) and q.get("error"):
            return _err(q["error"], symbol=symbol)
        px = float(q["price"])
        p = pt.create_portfolio(f"demo-{symbol}", 100000.0, "USD", 1.0, "cross", 0.001)
        pid = p["id"]
        o1 = pt.place_order(pid, symbol, "buy", "market", float(quantity), px)
        f1 = pt.fill_order(o1["id"], px)
        mark = round(px * 1.01, 2)
        pt.mark_price(pid, symbol, mark)
        o2 = pt.place_order(pid, symbol, "sell", "market", float(quantity), mark)
        f2 = pt.fill_order(o2["id"], mark)
        stats = pt.get_stats(pid)
        return _ok(
            {
                "symbol": symbol,
                "buy_price": px,
                "sell_price": mark,
                "portfolio_id": pid,
                "buy_fill": f1,
                "sell_fill": f2,
                "stats": stats,
            }
        )
    except Exception as e:
        return _err(str(e), symbol=symbol)


if __name__ == "__main__":
    mcp.run(transport="stdio")
