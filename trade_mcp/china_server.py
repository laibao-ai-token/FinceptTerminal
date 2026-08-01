#!/usr/bin/env python3
"""MCP server: china — limited akshare surface (A/HK hist, spot, index, china rates)."""
from __future__ import annotations

from typing import Optional

from mcp.server.fastmcp import FastMCP

from trade_mcp.common import ensure_script_paths, err, ok, trim_list

ensure_script_paths()
mcp = FastMCP("china")


import time as _time


def _yf_session():
    """Create a fresh requests.Session with proper User-Agent for yfinance.
    Avoids Yahoo's rate-limit 404 on the default urllib User-Agent."""
    import requests

    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    return s


def _yf_hist(yf_sym: str, start: str, end: str, auto_adjust: bool = False, retries: int = 3):
    """Fetch yfinance history with retry on rate-limit failures.
    Uses a fresh Session+Ticker per attempt to avoid poisoned cache state.
    Falls back to auto_adjust=False if auto_adjust=True raises (quoteSummary 404)."""
    import yfinance as yf

    last_df = None
    for attempt in range(retries):
        try:
            s = _yf_session()
            t = yf.Ticker(yf_sym, session=s)
            df = t.history(start=start, end=end, auto_adjust=auto_adjust)
            if df is not None and not df.empty:
                return df
            last_df = df
        except Exception:
            pass  # rate-limit 404 on quoteSummary — retry
        _time.sleep(0.5)
    # Last resort: try period="1mo" with auto_adjust=False
    try:
        s = _yf_session()
        t = yf.Ticker(yf_sym, session=s)
        df = t.history(period="1mo", auto_adjust=False)
        if df is not None and not df.empty:
            return df
    except Exception:
        pass
    return last_df


def _retry_akshare(func, *args, retries: int = 3, delay: float = 2.0, **kwargs):
    """Retry akshare calls that fail with connection errors (EastMoney rate-limit)."""
    last_err = None
    for attempt in range(retries):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                _time.sleep(delay * (attempt + 1))
            else:
                raise
    raise last_err  # type: ignore[misc]


def _trim_result(data, max_rows: int = 80):
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        data = dict(data)
        n = len(data["data"])
        if n > max_rows:
            data["data"] = data["data"][-max_rows:]
            data["trimmed_from"] = n
        return data
    return data


@mcp.tool()
def china_status() -> str:
    """Check akshare import and list china MCP tools scope."""
    try:
        import akshare as ak

        return ok(
            {
                "akshare": getattr(ak, "__version__", "unknown"),
                "scope": [
                    "A-share / HK hist",
                    "HK famous spot",
                    "index hist",
                    "China policy rate (akshare macro)",
                    "Baidu economic news",
                ],
            }
        )
    except Exception as e:
        return err(str(e))


@mcp.tool()
def a_share_hist(
    symbol: str = "000001",
    period: str = "daily",
    start_date: str = "20240101",
    end_date: str = "20261231",
    adjust: str = "qfq",
    max_rows: int = 80,
) -> str:
    """A-share daily history. symbol like 000001, 600519.
    Tries akshare (EastMoney) first, falls back to yfinance (.SS/.SZ) if unreachable.
    max_rows: how many most-recent rows to return (0 = all). Default 80."""
    import pandas as pd

    # Try akshare first (works when EastMoney is reachable)
    try:
        import akshare_stocks_historical as h

        data = h.get_stock_zh_a_hist(
            symbol=symbol, period=period,
            start_date=start_date, end_date=end_date, adjust=adjust,
        )
        if isinstance(data, dict) and data.get("success") is False:
            raise RuntimeError(str(data.get("error", "akshare failed")))
        return ok(_trim_result(data, max_rows))
    except Exception:
        pass  # fall through to yfinance

    # Fallback: yfinance — try both .SS and .SZ suffixes (don't guess):
    # Shanghai 600/601/603/688 stocks + 5xxxxx ETFs use .SS;
    # Shenzhen 000/001/300/301 stocks + 159xxx ETFs use .SZ.
    try:
        candidates = [f"{symbol}.SS", f"{symbol}.SZ"]
        sd = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}" if len(start_date) == 8 else start_date
        ed = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}" if len(end_date) == 8 else end_date
        df = None
        yf_sym_used = candidates[0]
        for yf_sym in candidates:
            df = _yf_hist(yf_sym, sd, ed, auto_adjust=False)
            if df is not None and not df.empty:
                yf_sym_used = yf_sym
                break
        if isinstance(df, type(None)) or df.empty:
            return ok({"success": True, "source": "yfinance", "data": [], "count": 0, "symbol": candidates[0], "note": "no data — market closed or symbol not found"})
        df = df.reset_index()
        df.columns = [str(c).replace(" ", "_").lower() for c in df.columns]
        for col in df.columns:
            if df[col].dtype == "datetime64[ns]":
                df[col] = df[col].astype(str)
        df = df.replace([float("inf"), float("-inf")], None).where(pd.notna(df), None)
        # drop rows with missing close (unclosed/suspended days)
        df = df[df["close"].notna()]
        rows = df.to_dict(orient="records")
        return ok(_trim_result({"success": True, "source": "yfinance", "symbol": yf_sym_used, "data": rows, "count": len(rows)}, max_rows))
    except Exception as e:
        return err(str(e), symbol=symbol, hint="Both akshare and yfinance failed")


@mcp.tool()
def hk_hist(
    symbol: str = "01810",
    period: str = "daily",
    start_date: str = "20240101",
    end_date: str = "20261231",
    adjust: str = "qfq",
) -> str:
    """HK stock history. symbol like 01810 (Xiaomi), 00700 (Tencent).
    Uses yfinance (1810.HK) directly — EastMoney (akshare) is unreachable from this host."""
    import pandas as pd

    try:
        sd = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}" if len(start_date) == 8 else start_date
        ed = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}" if len(end_date) == 8 else end_date
        # yfinance HK symbol format varies: 01810.HK works but 00700.HK doesn't;
        # 0700.HK (4-digit) works. Try 5-digit first, then 4-digit (strip leading
        # zeros and zero-pad to 4: 00700 → 0700, 00005 → 0005).
        candidates = [f"{symbol}.HK"]
        stripped = symbol.lstrip("0").zfill(4)
        if stripped != symbol and f"{stripped}.HK" not in candidates:
            candidates.append(f"{stripped}.HK")
        df = None
        yf_sym_used = candidates[0]
        for yf_sym in candidates:
            df = _yf_hist(yf_sym, sd, ed, auto_adjust=False)
            if df is not None and not df.empty:
                yf_sym_used = yf_sym
                break
        if isinstance(df, type(None)) or df.empty:
            return ok({"success": True, "source": "yfinance", "data": [], "count": 0, "symbol": yf_sym_used, "note": "no data — symbol may be delisted or market closed"})
        df = df.reset_index()
        df.columns = [str(c).replace(" ", "_").lower() for c in df.columns]
        for col in df.columns:
            if df[col].dtype == "datetime64[ns]":
                df[col] = df[col].astype(str)
        df = df.replace([float("inf"), float("-inf")], None).where(pd.notna(df), None)
        rows = df.to_dict(orient="records")
        return ok(_trim_result({"success": True, "source": "yfinance", "symbol": yf_sym, "data": rows, "count": len(rows)}, 80))
    except Exception as e:
        return err(str(e), symbol=symbol, hint="Both akshare and yfinance failed")


@mcp.tool()
def hk_spot_famous() -> str:
    """Famous HK names realtime spot (EastMoney)."""
    try:
        import akshare_stocks_realtime as r

        return ok(_trim_result(r.get_stock_hk_famous_spot_em(), max_rows=100))
    except Exception as e:
        return err(str(e))


@mcp.tool()
def a_share_spot_sample(limit: int = 30) -> str:
    """A-share spot snapshot sample (full market is huge; returns tail/limit rows)."""
    try:
        import akshare_stocks_realtime as r

        data = r.get_stock_zh_a_spot_em()
        if isinstance(data, dict) and isinstance(data.get("data"), list):
            rows = data["data"]
            data = dict(data)
            data["data"] = rows[: max(1, int(limit))]
            data["total_count"] = len(rows)
            data["sample"] = True
        return ok(data)
    except Exception as e:
        return err(str(e))


@mcp.tool()
def index_hist(
    symbol: str = "000001",
    period: str = "daily",
    start_date: str = "20240101",
    end_date: str = "20261231",
) -> str:
    """China index history. symbol e.g. 000001 (上证), 399001, 000300.
    Uses yfinance (.SS/.SZ suffixes) directly — EastMoney (akshare) is unreachable from this host."""
    import pandas as pd

    try:
        # A-shares: .SS (Shanghai) / .SZ (Shenzhen)
        if symbol.startswith("000") or symbol.startswith("600") or symbol.startswith("601"):
            yf_sym = f"{symbol}.SS"
        elif symbol.startswith("399"):
            yf_sym = f"{symbol}.SZ"
        else:
            yf_sym = f"^{symbol}"
        sd = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}" if len(start_date) == 8 else start_date
        ed = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}" if len(end_date) == 8 else end_date
        df = _yf_hist(yf_sym, sd, ed, auto_adjust=False)
        if isinstance(df, type(None)) or df.empty:
            return ok({"success": True, "source": "yfinance", "data": [], "count": 0, "symbol": yf_sym})
        df = df.reset_index()
        df.columns = [str(c).replace(" ", "_").lower() for c in df.columns]
        for col in df.columns:
            if df[col].dtype == "datetime64[ns]":
                df[col] = df[col].astype(str)
        df = df.replace([float("inf"), float("-inf")], None).where(pd.notna(df), None)
        rows = df.to_dict(orient="records")
        return ok(_trim_result({"success": True, "source": "yfinance", "symbol": yf_sym, "data": rows, "count": len(rows)}, 80))
    except Exception as e:
        return err(str(e), symbol=symbol, hint="Both akshare and yfinance failed")


@mcp.tool()
def index_global_spot() -> str:
    """Global index spot (akshare)."""
    try:
        import akshare_index as idx

        return ok(_trim_result(idx.get_index_global_spot(), max_rows=80))
    except Exception as e:
        return err(str(e))


@mcp.tool()
def china_policy_rate() -> str:
    """China central bank policy rate history (akshare macro)."""
    try:
        import akshare_macro as m

        w = m.MacroEconomicWrapper()
        data = w.macro_bank_china_interest_rate()
        if isinstance(data, dict) and isinstance(data.get("data"), list):
            data = dict(data)
            data["data"] = trim_list(data["data"], 40)
        return ok(data)
    except Exception as e:
        return err(str(e))


@mcp.tool()
def china_economic_news() -> str:
    """Baidu economic news feed (akshare)."""
    try:
        import akshare_news as n

        return ok(_trim_result(n.get_news_economic_baidu(), max_rows=30))
    except Exception as e:
        return err(str(e))


@mcp.tool()
def xiaomi_hk_snapshot(
    start_date: str = "20240101",
    end_date: str = "20261231",
) -> str:
    """Convenience: Xiaomi HK 01810 history + try match famous spot row."""
    try:
        import akshare_stocks_historical as h
        import akshare_stocks_realtime as r

        hist = _trim_result(
            h.get_stock_hk_hist(
                symbol="01810",
                period="daily",
                start_date=start_date,
                end_date=end_date,
                adjust="qfq",
            )
        )
        spot = r.get_stock_hk_famous_spot_em()
        row = None
        if isinstance(spot, dict) and isinstance(spot.get("data"), list):
            for item in spot["data"]:
                s = str(item)
                if "1810" in s or "小米" in s or "Xiaomi" in s.lower():
                    row = item
                    break
        return ok({"hist": hist, "spot_row": row})
    except Exception as e:
        return err(str(e))


if __name__ == "__main__":
    mcp.run(transport="stdio")
