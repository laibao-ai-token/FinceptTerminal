#!/usr/bin/env python3
"""MCP server: paper — headless paper trading only (no live brokerage)."""
from __future__ import annotations

from typing import Optional

from mcp.server.fastmcp import FastMCP

from trade_mcp.common import ensure_script_paths, err, ok

ensure_script_paths()
mcp = FastMCP("paper")


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
        return ok(pt.create_portfolio(name, float(balance), currency, 1.0, "cross", float(fee_rate)))
    except Exception as e:
        return err(str(e))


@mcp.tool()
def paper_list() -> str:
    """List all paper portfolios."""
    try:
        return ok(_pt().list_portfolios())
    except Exception as e:
        return err(str(e))


@mcp.tool()
def paper_reset(portfolio_id: str) -> str:
    """Reset portfolio to initial balance; clears positions/orders."""
    try:
        return ok(_pt().reset_portfolio(portfolio_id))
    except Exception as e:
        return err(str(e))


@mcp.tool()
def paper_delete(portfolio_id: str) -> str:
    """Delete a paper portfolio permanently."""
    try:
        return ok(_pt().delete_portfolio(portfolio_id))
    except Exception as e:
        return err(str(e))


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
        return ok(
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
        return err(str(e))


@mcp.tool()
def paper_cancel_order(order_id: str) -> str:
    """Cancel a pending paper order."""
    try:
        return ok(_pt().cancel_order(order_id))
    except Exception as e:
        return err(str(e))


@mcp.tool()
def paper_fill_order(order_id: str, price: float, quantity: Optional[float] = None) -> str:
    """Fill a pending paper order at given price."""
    try:
        pt = _pt()
        qty = float(quantity) if quantity is not None else None
        return ok(pt.fill_order(order_id, float(price), qty))
    except Exception as e:
        return err(str(e))


@mcp.tool()
def paper_orders(portfolio_id: str, status: str = "") -> str:
    """List orders. Optional status: open|filled|cancelled."""
    try:
        return ok(_pt().get_orders(portfolio_id, status))
    except Exception as e:
        return err(str(e))


@mcp.tool()
def paper_positions(portfolio_id: str) -> str:
    """List open positions for a portfolio."""
    try:
        return ok(_pt().get_positions(portfolio_id))
    except Exception as e:
        return err(str(e))


@mcp.tool()
def paper_stats(portfolio_id: str) -> str:
    """Portfolio stats: balance, pnl, trades, win_rate, fees."""
    try:
        pt = _pt()
        stats = pt.get_stats(portfolio_id)
        if isinstance(stats, dict):
            # attach live balance/currency from the portfolio table
            for p in pt.list_portfolios():
                if p.get("id") == portfolio_id:
                    stats["balance"] = p.get("balance", 0)
                    stats["initial_balance"] = p.get("initial_balance", 0)
                    stats["currency"] = p.get("currency", "")
                    break
        return ok(stats)
    except Exception as e:
        return err(str(e))


@mcp.tool()
def paper_mark(portfolio_id: str, symbol: str, price: float) -> str:
    """Mark symbol price for unrealized PnL / stop checks."""
    try:
        return ok(_pt().mark_price(portfolio_id, symbol, float(price)))
    except Exception as e:
        return err(str(e))


@mcp.tool()
def paper_check_stops(portfolio_id: str) -> str:
    """Evaluate SL/TP and stop orders against last marks."""
    try:
        return ok(_pt().check_stops(portfolio_id))
    except Exception as e:
        return err(str(e))


@mcp.tool()
def paper_buy(
    portfolio_id: str,
    symbol: str,
    quantity: float,
    price: Optional[float] = None,
) -> str:
    """Convenience: quote (if price omitted) + market buy + fill."""
    try:
        pt = _pt()
        if price is None:
            import yfinance_data as yf_data
            q = yf_data.get_quote(symbol)
            if isinstance(q, dict) and q.get("error"):
                return err(q["error"], symbol=symbol)
            price = float(q["price"])
        o = pt.place_order(portfolio_id, symbol, "buy", "market", float(quantity), float(price))
        if "error" in o:
            return ok(o)
        f = pt.fill_order(o["id"], float(price))
        return ok({"order": o, "fill": f, "price": price})
    except Exception as e:
        return err(str(e))


@mcp.tool()
def paper_sell(
    portfolio_id: str,
    symbol: str,
    quantity: float,
    price: Optional[float] = None,
) -> str:
    """Convenience: quote (if price omitted) + market sell + fill."""
    try:
        pt = _pt()
        if price is None:
            import yfinance_data as yf_data
            q = yf_data.get_quote(symbol)
            if isinstance(q, dict) and q.get("error"):
                return err(q["error"], symbol=symbol)
            price = float(q["price"])
        o = pt.place_order(portfolio_id, symbol, "sell", "market", float(quantity), float(price))
        if "error" in o:
            return ok(o)
        f = pt.fill_order(o["id"], float(price))
        return ok({"order": o, "fill": f, "price": price})
    except Exception as e:
        return err(str(e))


@mcp.tool()
def trade_loop_demo(symbol: str = "AAPL", quantity: float = 10.0) -> str:
    """End-to-end paper demo: create portfolio, buy, mark +1%, sell, return stats."""
    try:
        pt = _pt()
        import yfinance_data as yf_data
        q = yf_data.get_quote(symbol)
        if isinstance(q, dict) and q.get("error"):
            return err(q["error"], symbol=symbol)
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
        return ok({
            "symbol": symbol,
            "buy_price": px,
            "sell_price": mark,
            "portfolio_id": pid,
            "buy_fill": f1,
            "sell_fill": f2,
            "stats": stats,
        })
    except Exception as e:
        return err(str(e), symbol=symbol)


if __name__ == "__main__":
    mcp.run(transport="stdio")
