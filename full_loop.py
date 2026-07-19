"""
Full loop demo: pull a real AAPL quote via yfinance, then drive the headless
paper-trading engine through a complete buy->mark->sell cycle.

Usage:
  source .venv-pt/bin/activate
  python full_loop.py AAPL        # default symbol AAPL
"""
import json
import subprocess
import sys
import os
import yfinance as yf

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(HERE, "fincept-qt", "scripts", "paper_trading.py")
DB = "/root/.local/share/fincept/paper_trading.db"
if os.path.exists(DB):
    os.remove(DB)


def call(*args):
    out = subprocess.run([sys.executable, ENGINE, *args], capture_output=True, text=True)
    if out.returncode != 0 and not out.stdout.strip():
        raise RuntimeError(out.stderr or "engine failed")
    last = out.stdout.strip().splitlines()[-1] if out.stdout.strip() else "{}"
    try:
        obj = json.loads(last)
    except Exception:
        return {"_raw": out.stdout, "_err": out.stderr}
    if "error" in obj:
        raise RuntimeError(obj["error"])
    return obj


def quote(symbol):
    t = yf.Ticker(symbol)
    hist = t.history(period="1d")
    if hist.empty:
        raise RuntimeError("no data for " + symbol)
    return float(hist["Close"].iloc[-1])


def main():
    symbol = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    px = quote(symbol)
    print(f"[market] {symbol} live close = {px:.2f} (yfinance)")

    p = call("create_portfolio", json.dumps({"name": "loop", "balance": 100000, "fee_rate": 0.001}))
    pid = p["id"]
    print(f"[engine] portfolio {pid[:8]} balance={p['balance']:.2f}")

    qty = 10
    o = call("place_order", json.dumps({"portfolio_id": pid, "symbol": symbol,
                                         "side": "buy", "order_type": "market",
                                         "quantity": qty, "price": px}))
    f1 = call("fill_order", json.dumps({"order_id": o["id"], "price": px}))
    print(f"[engine] BUY  {qty} {symbol} @ {f1['price']:.2f}  fee={f1['fee']:.2f}  pnl={f1['pnl']:.2f}")

    # Mark a +1% move
    mark = round(px * 1.01, 2)
    call("mark", json.dumps({"portfolio_id": pid, "symbol": symbol, "price": mark}))
    pos = call("positions", json.dumps({"portfolio_id": pid}))
    print(f"[engine] marked @ {mark:.2f}  uPnL={pos[0]['unrealized_pnl']:.2f}")

    # check stops (no stops set here, just exercises the path)
    call("check_stops", json.dumps({"portfolio_id": pid}))

    o2 = call("place_order", json.dumps({"portfolio_id": pid, "symbol": symbol,
                                          "side": "sell", "order_type": "market",
                                          "quantity": qty, "price": mark}))
    f2 = call("fill_order", json.dumps({"order_id": o2["id"], "price": mark}))
    print(f"[engine] SELL {qty} {symbol} @ {f2['price']:.2f}  fee={f2['fee']:.2f}  pnl={f2['pnl']:.2f}")

    stats = call("stats", json.dumps({"portfolio_id": pid}))
    final = call("positions", json.dumps({"portfolio_id": pid}))
    print(f"[engine] positions left: {len(final)}")
    print(f"[engine] total_pnl={stats['total_pnl']:.2f}  trades={stats['total_trades']}  "
          f"win_rate={stats['win_rate']:.2f}  fees={stats['total_fees']:.2f}  profit_factor={stats['profit_factor']:.2f}")
    print("[done] yfinance -> paper-trading full loop verified OK")


if __name__ == "__main__":
    main()
