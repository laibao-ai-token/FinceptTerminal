#!/usr/bin/env python3
"""MCP server: market — quotes, history, company data, news, symbol search."""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from trade_mcp.common import ensure_script_paths, err, ok, trim_list

ensure_script_paths()
mcp = FastMCP("market")


@mcp.tool()
def market_quote(symbol: str) -> str:
    """Get latest market quote for a symbol (e.g. AAPL, NVDA, 1810.HK, XIACY)."""
    try:
        import yfinance_data as yf_data
        return ok(yf_data.get_quote(symbol))
    except Exception as e:
        return err(str(e), symbol=symbol)


@mcp.tool()
def market_history(symbol: str, period: str = "6mo", interval: str = "1d") -> str:
    """Get historical OHLCV. period: 1d,5d,1mo,3mo,6mo,1y,2y,5y,max. interval: 1d,1h,1wk."""
    try:
        import yfinance_data as yf_data
        data = yf_data.get_historical_period(symbol, period, interval)
        return ok(trim_list(data, 80) if isinstance(data, list) else data)
    except Exception as e:
        return err(str(e), symbol=symbol)


@mcp.tool()
def market_history_range(
    symbol: str,
    start_date: str,
    end_date: str,
    interval: str = "1d",
) -> str:
    """Historical OHLCV between start_date and end_date (YYYY-MM-DD)."""
    try:
        import yfinance_data as yf_data
        data = yf_data.get_historical(symbol, start_date, end_date, interval)
        return ok(trim_list(data, 80) if isinstance(data, list) else data)
    except Exception as e:
        return err(str(e), symbol=symbol)


@mcp.tool()
def batch_quotes(symbols: str) -> str:
    """Batch quotes. symbols: comma-separated tickers, e.g. 'AAPL,NVDA,1810.HK'."""
    try:
        import yfinance_data as yf_data
        syms = [s.strip() for s in symbols.split(",") if s.strip()]
        return ok(yf_data.get_batch_quotes(syms))
    except Exception as e:
        return err(str(e), symbols=symbols)


@mcp.tool()
def company_info(symbol: str) -> str:
    """Company info: sector, market cap, PE, beta, description, analyst targets, etc."""
    try:
        import yfinance_data as yf_data
        return ok(yf_data.get_info(symbol))
    except Exception as e:
        return err(str(e), symbol=symbol)


@mcp.tool()
def company_profile(symbol: str) -> str:
    """Company profile for peer-style comparison (name, sector, mcap, country...)."""
    try:
        import yfinance_data as yf_data
        return ok(yf_data.get_company_profile(symbol))
    except Exception as e:
        return err(str(e), symbol=symbol)


@mcp.tool()
def financial_ratios(symbol: str) -> str:
    """Key financial ratios (valuation, profitability, leverage proxies from yfinance)."""
    try:
        import yfinance_data as yf_data
        return ok(yf_data.get_financial_ratios(symbol))
    except Exception as e:
        return err(str(e), symbol=symbol)


@mcp.tool()
def financials(symbol: str) -> str:
    """Financial statements summary (income/balance/cashflow extracts)."""
    try:
        import yfinance_data as yf_data
        return ok(yf_data.get_financials(symbol))
    except Exception as e:
        return err(str(e), symbol=symbol)


@mcp.tool()
def symbol_search(query: str, limit: int = 20) -> str:
    """Search ticker symbols by company name or keyword."""
    try:
        import yfinance_data as yf_data
        return ok(yf_data.search_symbols(query, int(limit)))
    except Exception as e:
        return err(str(e), query=query)


@mcp.tool()
def news_search(query: str, max_results: int = 10) -> str:
    """Search company/market news via yfinance. query = ticker (AAPL) or name; non-ticker auto-resolves."""
    try:
        import yfinance_data as yf_data
        sym = query.strip()
        # yfinance get_news only works with real tickers; resolve name→ticker
        if sym and not any(sym.endswith(s) for s in (".HK", ".NS", ".BO", ".SH", ".SZ")):
            import re
            if not re.match(r'^[A-Z]{1,5}$', sym):
                # looks like a name, not a ticker → search_symbols first
                sr = yf_data.search_symbols(sym, limit=1)
                if isinstance(sr, dict) and isinstance(sr.get("results"), list) and sr["results"]:
                    sym = sr["results"][0].get("symbol", sym)
        result = yf_data.get_news(sym, count=int(max_results))
        articles = result.get("articles", []) if isinstance(result, dict) else (result if isinstance(result, list) else [])
        return ok({
            "query": query,
            "resolved_symbol": sym,
            "count": len(articles),
            "data": articles,
        })
    except Exception as e:
        return err(str(e), query=query)



@mcp.tool()
def batch_sparklines(symbols: str, period: str = "5d", interval: str = "1h") -> str:
    """Batch mini price series for sparklines. symbols comma-separated."""
    try:
        import yfinance_data as yf_data
        syms = [s.strip() for s in symbols.split(",") if s.strip()]
        return ok(yf_data.get_batch_sparklines(syms, period, interval))
    except Exception as e:
        return err(str(e), symbols=symbols)


@mcp.tool()
def multiple_profiles(symbols: str) -> str:
    """Company profiles for multiple symbols (comma-separated)."""
    try:
        import yfinance_data as yf_data
        syms = [s.strip() for s in symbols.split(",") if s.strip()]
        return ok(yf_data.get_multiple_profiles(syms))
    except Exception as e:
        return err(str(e), symbols=symbols)


@mcp.tool()
def multiple_ratios(symbols: str) -> str:
    """Financial ratios for multiple symbols (comma-separated)."""
    try:
        import yfinance_data as yf_data
        syms = [s.strip() for s in symbols.split(",") if s.strip()]
        return ok(yf_data.get_multiple_ratios(syms))
    except Exception as e:
        return err(str(e), symbols=symbols)


@mcp.tool()
def historical_price(symbol: str, target_date: str) -> str:
    """Closing price near a target date (YYYY-MM-DD)."""
    try:
        import yfinance_data as yf_data
        return ok(yf_data.get_historical_price(symbol, target_date))
    except Exception as e:
        return err(str(e), symbol=symbol, target_date=target_date)


@mcp.tool()
def portfolio_nav_replay(transactions_json: str) -> str:
    """Replay true NAV from transactions JSON list (buys/sells over time)."""
    try:
        import json as _json
        import yfinance_data as yf_data
        tx = _json.loads(transactions_json)
        data = yf_data.get_portfolio_nav_history_replay(tx)
        if isinstance(data, list):
            return ok(trim_list(data, 40))
        return ok(data)
    except Exception as e:
        return err(str(e))


@mcp.tool()
def batch_all(payload_json: str) -> str:
    """Batch multi-action yfinance payload (JSON string for get_batch_all)."""
    try:
        import json as _json
        import yfinance_data as yf_data
        payload = _json.loads(payload_json)
        return ok(yf_data.get_batch_all(payload))
    except Exception as e:
        return err(str(e))


if __name__ == "__main__":
    mcp.run(transport="stdio")
