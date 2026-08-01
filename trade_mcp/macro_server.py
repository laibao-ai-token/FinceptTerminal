#!/usr/bin/env python3
"""MCP server: macro — FRED (key optional) + World Bank free + FRED extended bundles."""
from __future__ import annotations

import os
import pandas as pd
from typing import Optional

from mcp.server.fastmcp import FastMCP

from trade_mcp.common import ensure_script_paths, err, ok, trim_list

ensure_script_paths()
mcp = FastMCP("macro")

# Common FRED series for asset agents
KEY_SERIES = {
    "cpi": "CPIAUCSL",
    "core_cpi": "CPILFESL",
    "unrate": "UNRATE",
    "fed_funds": "FEDFUNDS",
    "gdp": "GDP",
    "payrolls": "PAYEMS",
    "pce": "PCEPI",
    "core_pce": "PCEPILFE",
    "dgs10": "DGS10",
    "dgs2": "DGS2",
    "t10y2y": "T10Y2Y",
    "vix": "VIXCLS",
    "m2": "M2SL",
}


def _latest_from_obs(data: dict) -> dict:
    if not isinstance(data, dict):
        return {"error": "bad series payload"}
    if data.get("error"):
        return data
    obs = data.get("observations") or []
    last = obs[-1] if obs else None
    return {
        "series_id": data.get("series_id"),
        "title": data.get("title"),
        "units": data.get("units"),
        "frequency": data.get("frequency"),
        "latest": last,
        "observation_count": data.get("observation_count", len(obs)),
    }


@mcp.tool()
def fred_status() -> str:
    """Whether FRED_API_KEY is configured (required for fred_* tools)."""
    key = os.environ.get("FRED_API_KEY", "")
    return ok(
        {
            "configured": bool(key),
            "hint": "Set FRED_API_KEY for FRED series; World Bank tools work without a key.",
            "key_series": KEY_SERIES,
        }
    )


@mcp.tool()
def fred_search(query: str, limit: int = 10) -> str:
    """Search FRED series by text (needs FRED_API_KEY)."""
    try:
        import fred_data as fred

        return ok(fred.search_series(query, int(limit)))
    except Exception as e:
        return err(str(e), query=query)


@mcp.tool()
def fred_series(
    series_id: str,
    start_date: str = "",
    end_date: str = "",
    frequency: str = "",
    transform: str = "",
) -> str:
    """Fetch FRED series observations (e.g. CPIAUCSL, UNRATE, FEDFUNDS). Needs FRED_API_KEY."""
    try:
        import fred_data as fred

        data = fred.get_series(
            series_id,
            start_date=start_date or None,
            end_date=end_date or None,
            frequency=frequency or None,
            transform=transform or None,
        )
        if isinstance(data, dict) and isinstance(data.get("observations"), list):
            data = dict(data)
            data["observations"] = trim_list(data["observations"], 80)
            if isinstance(data["observations"], dict):
                # trim_list wrapped
                pass
        return ok(data)
    except Exception as e:
        return err(str(e), series_id=series_id)


@mcp.tool()
def fred_latest(series_id: str) -> str:
    """Latest observation for a FRED series id."""
    try:
        import fred_data as fred

        return ok(_latest_from_obs(fred.get_series(series_id)))
    except Exception as e:
        return err(str(e), series_id=series_id)


@mcp.tool()
def fred_batch_latest(series_ids: str = "") -> str:
    """Latest points for comma-separated FRED ids. Empty = default key macro set."""
    try:
        import fred_data as fred

        if series_ids.strip():
            ids = [s.strip() for s in series_ids.split(",") if s.strip()]
        else:
            ids = list(KEY_SERIES.values())
        out = {}
        for sid in ids:
            out[sid] = _latest_from_obs(fred.get_series(sid))
        return ok({"series": out, "count": len(out)})
    except Exception as e:
        return err(str(e))


@mcp.tool()
def fred_key_indicators(start_date: str = "", end_date: str = "") -> str:
    """Batch named key macro series (cpi, unrate, fed_funds, dgs10, t10y2y, vix, m2)."""
    try:
        import fred_data as fred

        out = {}
        for name, sid in KEY_SERIES.items():
            data = fred.get_series(sid, start_date=start_date or None, end_date=end_date or None)
            out[name] = _latest_from_obs(data)
        return ok(out)
    except Exception as e:
        return err(str(e))


@mcp.tool()
def fred_yield_curve(start_date: str = "", end_date: str = "") -> str:
    """US Treasury yield curve bundle from FRED extended module."""
    try:
        import fred_economic_data as fx

        return ok(fx.get_yield_curve(start_date=start_date, end_date=end_date))
    except Exception as e:
        return err(str(e))


@mcp.tool()
def fred_money_supply(measure: str = "m2", start_date: str = "", end_date: str = "") -> str:
    """Money supply (m1/m2/velocity/base/reserves). Needs FRED_API_KEY."""
    try:
        import fred_economic_data as fx

        return ok(fx.get_money_supply(measure=measure, start_date=start_date, end_date=end_date))
    except Exception as e:
        return err(str(e), measure=measure)


@mcp.tool()
def fred_credit_conditions(
    series_id: str = "fed_funds_rate", start_date: str = "", end_date: str = ""
) -> str:
    """Credit conditions series key (fed_funds_rate, sofr, mortgage_rate_30y, ...)."""
    try:
        import fred_economic_data as fx

        return ok(fx.get_credit_conditions(series_id=series_id, start_date=start_date, end_date=end_date))
    except Exception as e:
        return err(str(e), series_id=series_id)


@mcp.tool()
def fred_financial_stress(start_date: str = "", end_date: str = "") -> str:
    """Financial stress indices (STLFSI, NFCI, TED, VIX, ...)."""
    try:
        import fred_economic_data as fx

        return ok(fx.get_financial_stress_index(start_date=start_date, end_date=end_date))
    except Exception as e:
        return err(str(e))


@mcp.tool()
def worldbank_indicator(
    country_code: str = "US",
    indicator: str = "NY.GDP.MKTP.KD.ZG",
    date_range: str = "",
) -> str:
    """World Bank indicator (no API key). e.g. GDP growth NY.GDP.MKTP.KD.ZG, inflation FP.CPI.TOTL.ZG."""
    try:
        import worldbank_data as wb

        return ok(
            wb.get_indicators(
                country_code=country_code,
                indicator=indicator,
                date_range=date_range or None,
            )
        )
    except Exception as e:
        return err(str(e), country_code=country_code, indicator=indicator)


@mcp.tool()
def worldbank_snapshot(country_code: str = "USA") -> str:
    """Country economic snapshot via World Bank (partial OK if some indicators fail)."""
    try:
        import worldbank_data as wb

        # Prefer robust per-indicator fetch (full snapshot can timeout)
        code = country_code
        # World Bank accepts USA or US depending on endpoint; try both via indicators
        indicators = {
            "gdp_growth": "NY.GDP.MKTP.KD.ZG",
            "gdp_per_capita": "NY.GDP.PCAP.CD",
            "inflation": "FP.CPI.TOTL.ZG",
            "unemployment": "SL.UEM.TOTL.ZS",
        }
        out = {"country_code": code, "indicators": {}, "errors": {}}
        for name, ind in indicators.items():
            try:
                r = wb.get_indicators(country_code=code if len(code) <= 3 else code[:2] if code == "USA" else code, indicator=ind)
                # normalize USA -> try US if empty
                if isinstance(r, dict) and (r.get("error") or not r.get("data")):
                    alt = "US" if code.upper() in ("USA", "US") else code
                    r = wb.get_indicators(country_code=alt, indicator=ind)
                if isinstance(r, dict) and r.get("error"):
                    out["errors"][name] = r.get("error")
                else:
                    rows = (r or {}).get("data") if isinstance(r, dict) else None
                    latest = None
                    if isinstance(rows, list) and rows:
                        for row in rows:
                            if row.get("value") is not None:
                                latest = row
                                break
                        if latest is None:
                            latest = rows[0]
                    out["indicators"][name] = latest or r
            except Exception as ex:
                out["errors"][name] = str(ex)
        if not out["indicators"] and out["errors"]:
            return err("all snapshot indicators failed", **out)
        return ok(out)
    except Exception as e:
        return err(str(e), country_code=country_code)


@mcp.tool()
def worldbank_gdp_per_capita(countries: str = "USA,CHN", years: int = 15) -> str:
    """GDP per capita comparison for comma-separated country codes."""
    try:
        import worldbank_data as wb

        return ok(wb.get_gdp_per_capita(countries=countries, years=int(years)))
    except Exception as e:
        return err(str(e), countries=countries)


@mcp.tool()
def china_bond_yield(days: int = 10) -> str:
    """China (and US) government bond yields via akshare bond_zh_us_rate (Sina data).
    Returns latest rows with 2y/5y/10y/30y yields for CN and US."""
    try:
        import akshare as ak

        df = ak.bond_zh_us_rate(start_date="20200101")
        if df is None or len(df) == 0:
            return err("no bond yield data returned")
        df = df.sort_values("日期").tail(max(1, int(days)))
        df = df.replace([float("inf"), float("-inf")], None).where(pd.notna(df), None)
        rows = df.to_dict(orient="records")
        return ok({
            "source": "akshare bond_zh_us_rate (Sina)",
            "note": "percent annual yields; CN=China, US=United States",
            "count": len(rows),
            "data": rows,
        })
    except Exception as e:
        return err(str(e), hint="bond_zh_us_rate failed")


if __name__ == "__main__":
    mcp.run(transport="stdio")
