#!/usr/bin/env python3
"""MCP server: fundamentals — SEC Edgar, FX (Frankfurter), GNews."""
from __future__ import annotations

import os
from typing import Optional

from mcp.server.fastmcp import FastMCP

from trade_mcp.common import ensure_script_paths, err, ok, trim_list

ensure_script_paths()
mcp = FastMCP("fundamentals")

# Edgar identity for SEC fair access (override with EDGAR_IDENTITY env)
_DEFAULT_IDENTITY = os.environ.get("EDGAR_IDENTITY", "trade-agent@localhost")


def _edgar_init():
    """Lazy-load Fincept edgar modules as package (do not shadow edgartools)."""
    import sys
    import types
    import importlib.util
    from trade_mcp.common import SCRIPTS

    # Ensure official edgartools wins for `import edgar`
    bad = str(SCRIPTS / "mcp")
    while bad in sys.path:
        sys.path.remove(bad)
    # Prefer site-packages for name `edgar`
    try:
        import edgar as _edgartools  # noqa: F401
        # If wrong package (local), force reload from site-packages
        if "scripts/mcp/edgar" in str(getattr(_edgartools, "__file__", "")):
            # drop shadow and reimport
            for k in list(sys.modules):
                if k == "edgar" or k.startswith("edgar."):
                    del sys.modules[k]
            import edgar as _edgartools  # noqa: F401
    except Exception:
        pass

    root_pkg = "fincept_edgar_pkg"
    edgar_dir = SCRIPTS / "mcp" / "edgar"
    if root_pkg not in sys.modules:
        pkg = types.ModuleType(root_pkg)
        pkg.__path__ = [str(edgar_dir)]
        pkg.__package__ = root_pkg
        sys.modules[root_pkg] = pkg

    def load(name: str):
        full = f"{root_pkg}.{name}"
        if full in sys.modules:
            return sys.modules[full]
        path = edgar_dir / f"{name}.py"
        spec = importlib.util.spec_from_file_location(
            full, path, submodule_search_locations=[str(edgar_dir)]
        )
        mod = importlib.util.module_from_spec(spec)
        mod.__package__ = root_pkg
        sys.modules[full] = mod
        assert spec.loader is not None
        spec.loader.exec_module(mod)
        return mod

    base = load("base")
    financials = load("financials")
    forms_10k = load("forms_10k")
    forms_10q = load("forms_10q")
    forms_8k = load("forms_8k")
    forms_13f = load("forms_13f")
    return base, financials, forms_10k, forms_10q, forms_8k, forms_13f



@mcp.tool()
def edgar_status() -> str:
    """Check whether SEC Edgar toolkit is importable and identity is set."""
    try:
        base, *_ = _edgar_init()
        avail = base.check_edgar_available()
        init = base.initialize_edgar(_DEFAULT_IDENTITY)
        return ok({"available": avail, "init": init, "identity": _DEFAULT_IDENTITY})
    except Exception as e:
        return err(str(e))


@mcp.tool()
def edgar_find_company(query: str, top_n: int = 10) -> str:
    """Search companies on SEC Edgar by name."""
    try:
        base, *_ = _edgar_init()
        base.initialize_edgar(_DEFAULT_IDENTITY)
        return ok(base.find_company_by_name(query, int(top_n)))
    except Exception as e:
        return err(str(e), query=query)


@mcp.tool()
def edgar_company_info(ticker: str) -> str:
    """SEC company info for a ticker."""
    try:
        base, *_ = _edgar_init()
        base.initialize_edgar(_DEFAULT_IDENTITY)
        return ok(base.get_company_info(ticker))
    except Exception as e:
        return err(str(e), ticker=ticker)


@mcp.tool()
def edgar_financials(ticker: str, periods: int = 4, annual: bool = True) -> str:
    """SEC-filed financial statements extract for ticker."""
    try:
        base, financials, *_ = _edgar_init()
        base.initialize_edgar(_DEFAULT_IDENTITY)
        return ok(financials.get_financials(ticker, int(periods), bool(annual)))
    except Exception as e:
        return err(str(e), ticker=ticker)


@mcp.tool()
def edgar_financial_metrics(ticker: str) -> str:
    """Key financial metrics from SEC filings."""
    try:
        base, financials, *_ = _edgar_init()
        base.initialize_edgar(_DEFAULT_IDENTITY)
        return ok(financials.get_financial_metrics(ticker))
    except Exception as e:
        return err(str(e), ticker=ticker)


@mcp.tool()
def edgar_10k_meta(ticker: str) -> str:
    """Latest 10-K metadata for ticker."""
    try:
        base, _, forms_10k, *_ = _edgar_init()
        base.initialize_edgar(_DEFAULT_IDENTITY)
        return ok(forms_10k.get_10k_metadata(ticker))
    except Exception as e:
        return err(str(e), ticker=ticker)


@mcp.tool()
def edgar_10k_sections(ticker: str, sections: str = "business,risk_factors") -> str:
    """Extract 10-K sections. sections comma-separated e.g. business,risk_factors."""
    try:
        base, _, forms_10k, *_ = _edgar_init()
        base.initialize_edgar(_DEFAULT_IDENTITY)
        sec_list = [s.strip() for s in sections.split(",") if s.strip()] or None
        data = forms_10k.extract_10k_sections(ticker, sec_list)
        # trim huge text
        if isinstance(data, dict):
            for k, v in list(data.items()):
                if isinstance(v, str) and len(v) > 4000:
                    data[k] = v[:4000] + "...[truncated]"
        return ok(data)
    except Exception as e:
        return err(str(e), ticker=ticker)


@mcp.tool()
def edgar_8k_events(ticker: str, limit: int = 20) -> str:
    """Recent 8-K events for ticker."""
    try:
        base, _, _, _, forms_8k, _ = _edgar_init()
        base.initialize_edgar(_DEFAULT_IDENTITY)
        return ok(forms_8k.get_8k_events(ticker, int(limit)))
    except Exception as e:
        return err(str(e), ticker=ticker)


@mcp.tool()
def edgar_13f_top(ticker: str, top_n: int = 20) -> str:
    """Top 13F holdings for an institutional manager ticker."""
    try:
        base, _, _, _, _, forms_13f = _edgar_init()
        base.initialize_edgar(_DEFAULT_IDENTITY)
        return ok(forms_13f.get_13f_top_holdings(ticker, int(top_n)))
    except Exception as e:
        return err(str(e), ticker=ticker)


@mcp.tool()
def edgar_search_filings(ticker: str, form: str = "8-K", months_back: int = 12) -> str:
    """Search recent SEC filings for ticker by form type."""
    try:
        base, *_ = _edgar_init()
        base.initialize_edgar(_DEFAULT_IDENTITY)
        return ok(base.search_filings(ticker, form, int(months_back)))
    except Exception as e:
        return err(str(e), ticker=ticker)


@mcp.tool()
def fx_latest(base: str = "USD", symbols: str = "EUR,GBP,JPY,CNY,HKD") -> str:
    """Latest ECB FX rates via Frankfurter. base currency + comma-separated targets."""
    try:
        import frankfurter_data as fx
        return ok(fx.get_latest(base=base, symbols=symbols))
    except Exception as e:
        return err(str(e))


@mcp.tool()
def fx_historical(date: str, base: str = "USD", symbols: str = "EUR,GBP,JPY") -> str:
    """Historical FX rates for a date (YYYY-MM-DD)."""
    try:
        import frankfurter_data as fx
        return ok(fx.get_historical(date, base=base, symbols=symbols))
    except Exception as e:
        return err(str(e), date=date)


@mcp.tool()
def fx_series(start_date: str, end_date: str = "", base: str = "USD", symbols: str = "EUR") -> str:
    """FX time series from start_date to end_date (optional) via Frankfurter."""
    try:
        import frankfurter_data as fx
        end = end_date or None
        data = fx.get_time_series(start_date, end, base=base, symbols=symbols)
        return ok(data)
    except Exception as e:
        return err(str(e), start_date=start_date)


@mcp.tool()
def company_news_gnews(
    query: str,
    max_results: int = 10,
    period: str = "7d",
    language: str = "en",
    country: str = "US",
) -> str:
    """Company/market news via GNews (fetch_company_news)."""
    try:
        from fetch_company_news import fetch_company_news
        raw = fetch_company_news(query, int(max_results), period, language, country)
        # function returns JSON string
        if isinstance(raw, str):
            import json as _json
            try:
                return ok(_json.loads(raw))
            except Exception:
                return ok({"raw": raw[:2000]})
        return ok(raw)
    except Exception as e:
        return err(str(e), query=query)


if __name__ == "__main__":
    mcp.run(transport="stdio")
