#!/usr/bin/env python3
"""MCP server: research — backtest, indicators, portfolio optimize/nav."""
from __future__ import annotations

import json
import subprocess
from typing import Optional

from mcp.server.fastmcp import FastMCP

from trade_mcp.common import PY, ROOT, SCRIPTS, ensure_script_paths, err, ok, trim_list

ensure_script_paths()
mcp = FastMCP("research")


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
            data = result.get("data")
            if isinstance(data, dict) and isinstance(data.get("equity"), list):
                data = dict(data)
                data["equity"] = trim_list(data["equity"], 20)
                result = dict(result)
                result["data"] = data
            for key in ("equityCurve", "equity_curve", "trades", "returns"):
                if key in result and isinstance(result[key], list) and len(result[key]) > 50:
                    result[key] = trim_list(result[key], 20)
        return ok(result)
    except Exception as e:
        return err(str(e), symbol=symbol, strategy=strategy)


@mcp.tool()
def backtest_strategies() -> str:
    """List available backtest strategy types."""
    try:
        from bt_provider import BtProvider
        return ok(BtProvider().get_strategies({}))
    except Exception as e:
        return err(str(e))


@mcp.tool()
def backtest_optimize(
    symbol: str,
    strategy: str = "sma_crossover",
    start_date: str = "2024-01-01",
    end_date: str = "2024-12-31",
) -> str:
    """Optimize strategy parameters (bt provider optimize command)."""
    try:
        from bt_provider import BtProvider
        req = {
            "strategy": {"type": strategy, "params": {}},
            "symbols": [symbol],
            "startDate": start_date,
            "endDate": end_date,
            "initialCapital": 100000,
        }
        return ok(BtProvider().optimize(req))
    except Exception as e:
        return err(str(e), symbol=symbol)


@mcp.tool()
def calculate_indicator(
    symbol: str,
    indicator: str = "sma",
    period: str = "6mo",
    length: int = 20,
) -> str:
    """Calculate a technical indicator via bt provider. indicator e.g. sma, ema, rsi."""
    try:
        from bt_provider import BtProvider
        req = {
            "symbol": symbol,
            "indicator": indicator,
            "period": period,
            "params": {"length": int(length)},
            "symbols": [symbol],
        }
        return ok(BtProvider().calculate_indicator(req))
    except Exception as e:
        return err(str(e), symbol=symbol, indicator=indicator)


@mcp.tool()
def analyze_returns(symbol: str, start_date: str = "2024-01-01", end_date: str = "2024-12-31") -> str:
    """Analyze return statistics for a symbol over a date range."""
    try:
        from bt_provider import BtProvider
        req = {
            "symbols": [symbol],
            "startDate": start_date,
            "endDate": end_date,
        }
        return ok(BtProvider().analyze_returns(req))
    except Exception as e:
        return err(str(e), symbol=symbol)


@mcp.tool()
def portfolio_optimize(
    symbols: str,
    method: str = "max_sharpe",
    period: str = "1y",
) -> str:
    """Optimize portfolio weights. symbols comma-separated. method: max_sharpe,min_volatility,risk_parity,equal_weight,hrp."""
    try:
        syms = [s.strip() for s in symbols.split(",") if s.strip()]
        if len(syms) < 2:
            return err("need at least 2 symbols", symbols=symbols)
        n = len(syms)
        payload = {
            "symbols": syms,
            "weights": [1.0 / n] * n,
            "method": method,
            "period": period,
        }
        script = SCRIPTS / "optimize_portfolio_weights.py"
        proc = subprocess.run(
            [PY, str(script), "--args", json.dumps(payload)],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(ROOT),
        )
        out = (proc.stdout or "").strip().splitlines()
        if not out:
            return err(proc.stderr or "no output", code=proc.returncode)
        try:
            return ok(json.loads(out[-1]))
        except Exception:
            return err("bad json from optimizer", raw=out[-1][:500], stderr=proc.stderr[-500:] if proc.stderr else "")
    except Exception as e:
        return err(str(e), symbols=symbols)


@mcp.tool()
def portfolio_nav(positions_json: str, period: str = "6mo") -> str:
    """Portfolio NAV history. positions_json e.g. '[{\"symbol\":\"AAPL\",\"quantity\":10},{\"symbol\":\"MSFT\",\"quantity\":5}]'."""
    try:
        import yfinance_data as yf_data
        positions = json.loads(positions_json)
        return ok(trim_list(yf_data.get_portfolio_nav_history(positions, period), 40))
    except Exception as e:
        return err(str(e))



def _bt_req(symbol: str, strategy: str, start_date: str, end_date: str, initial_capital: float = 100000.0) -> dict:
    return {
        "strategy": {"type": strategy, "params": {}},
        "symbols": [symbol],
        "startDate": start_date,
        "endDate": end_date,
        "initialCapital": float(initial_capital),
        "commission": 0.001,
    }


@mcp.tool()
def backtest_walk_forward(
    symbol: str,
    strategy: str = "sma_crossover",
    start_date: str = "2024-01-01",
    end_date: str = "2024-12-31",
) -> str:
    """Walk-forward backtest validation for a symbol/strategy."""
    try:
        from bt_provider import BtProvider
        return ok(BtProvider().walk_forward(_bt_req(symbol, strategy, start_date, end_date)))
    except Exception as e:
        return err(str(e), symbol=symbol)


@mcp.tool()
def list_indicators() -> str:
    """List technical indicators supported by bt provider."""
    try:
        from bt_provider import BtProvider
        return ok(BtProvider().get_indicators({}))
    except Exception as e:
        return err(str(e))


@mcp.tool()
def indicator_signals(
    symbol: str,
    indicator: str = "sma",
    period: str = "6mo",
    length: int = 20,
) -> str:
    """Generate indicator signals for a symbol."""
    try:
        from bt_provider import BtProvider
        req = {
            "symbol": symbol,
            "indicator": indicator,
            "period": period,
            "params": {"length": int(length)},
            "symbols": [symbol],
        }
        return ok(BtProvider().indicator_signals(req))
    except Exception as e:
        return err(str(e), symbol=symbol)


@mcp.tool()
def generate_signals(
    symbol: str,
    strategy: str = "sma_crossover",
    start_date: str = "2024-01-01",
    end_date: str = "2024-12-31",
) -> str:
    """Generate trading signals for strategy without full backtest equity curve bloat."""
    try:
        from bt_provider import BtProvider
        return ok(BtProvider().generate_signals(_bt_req(symbol, strategy, start_date, end_date)))
    except Exception as e:
        return err(str(e), symbol=symbol)


@mcp.tool()
def get_command_options() -> str:
    """List bt provider command options / capabilities."""
    try:
        from bt_provider import BtProvider
        return ok(BtProvider().get_command_options({}))
    except Exception as e:
        return err(str(e))


@mcp.tool()
def quantstats_report(symbols: str, weights: str = "", period: str = "1y") -> str:
    """QuantStats performance report. symbols comma-separated; weights optional comma floats (equal if empty)."""
    try:
        syms = [s.strip() for s in symbols.split(",") if s.strip()]
        if not syms:
            return err("need at least 1 symbol")
        if weights.strip():
            w = [float(x) for x in weights.split(",") if x.strip()]
        else:
            w = [1.0 / len(syms)] * len(syms)
        if len(w) != len(syms):
            return err("weights length must match symbols", n_sym=len(syms), n_w=len(w))
        # Prefer in-process
        try:
            import quantstats_analysis as qs
            return ok(qs.compute_stats(syms, w, period=period))
        except Exception:
            pass
        payload = {"symbols": syms, "weights": w, "period": period}
        script = SCRIPTS / "quantstats_analysis.py"
        proc = subprocess.run(
            [PY, str(script)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=180,
            cwd=str(ROOT),
        )
        out = (proc.stdout or "").strip().splitlines()
        if not out:
            return err(proc.stderr or "quantstats no output", code=proc.returncode)
        try:
            return ok(json.loads(out[-1]))
        except Exception:
            return err("bad quantstats json", raw=out[-1][:500], stderr=(proc.stderr or "")[-500:])
    except Exception as e:
        return err(str(e), symbols=symbols)



@mcp.tool()
def signals_to_paper(
    portfolio_id: str,
    symbol: str,
    strategy: str = "sma_crossover",
    start_date: str = "2024-01-01",
    end_date: str = "2024-12-31",
    quantity: float = 10.0,
    dry_run: bool = True,
) -> str:
    """Bridge: generate strategy signals → optional paper buy/sell on last signal.

    dry_run=True (default): only report last signal + would-be action, no orders.
    dry_run=False: execute paper_buy (signal>0) or paper_sell (signal<0) once.
    signal==0 → hold / no trade.
    """
    try:
        from bt_provider import BtProvider
        import paper_trading as pt

        raw = BtProvider().generate_signals(
            _bt_req(symbol, strategy, start_date, end_date)
        )
        signals = []
        if isinstance(raw, dict):
            data = raw.get("data") if "data" in raw else raw
            if isinstance(data, dict):
                sig_map = data.get("signals") or data
                if isinstance(sig_map, dict) and symbol in sig_map:
                    signals = sig_map[symbol] or []
                elif isinstance(sig_map, dict):
                    # first symbol
                    for _k, v in sig_map.items():
                        if isinstance(v, list):
                            signals = v
                            break
            elif isinstance(data, list):
                signals = data
        if not signals:
            return err("no signals produced", symbol=symbol, raw_keys=list(raw.keys()) if isinstance(raw, dict) else type(raw).__name__)

        last = signals[-1]
        sig_val = last.get("signal") if isinstance(last, dict) else last
        try:
            sig_val = float(sig_val)
        except Exception:
            sig_val = 0.0

        action = "hold"
        if sig_val > 0:
            action = "buy"
        elif sig_val < 0:
            action = "sell"

        result = {
            "symbol": symbol,
            "strategy": strategy,
            "last_signal": last,
            "action": action,
            "quantity": float(quantity),
            "dry_run": bool(dry_run),
            "signal_count": len(signals),
        }

        if dry_run or action == "hold":
            result["executed"] = False
            return ok(result)

        # live paper path
        import yfinance_data as yf_data

        q = yf_data.get_quote(symbol)
        if isinstance(q, dict) and q.get("error"):
            return err(q["error"], symbol=symbol, partial=result)
        price = float(q["price"])
        side = "buy" if action == "buy" else "sell"
        o = pt.place_order(portfolio_id, symbol, side, "market", float(quantity), price)
        if isinstance(o, dict) and o.get("error"):
            result["order_error"] = o
            result["executed"] = False
            return ok(result)
        f = pt.fill_order(o["id"], price)
        result["executed"] = True
        result["price"] = price
        result["order"] = o
        result["fill"] = f
        return ok(result)
    except Exception as e:
        return err(str(e), symbol=symbol, portfolio_id=portfolio_id)


if __name__ == "__main__":
    mcp.run(transport="stdio")
