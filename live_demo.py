"""
Live integration demo: pull a real market quote, then run it through the
headless paper-trading engine (paper_trading.py). No Qt / compilation needed.

Usage:
  source .venv-pt/bin/activate
  python live_demo.py          # uses frankfurter (no key) for a FX pair
  python live_demo.py AAPL     # uses yfinance if installed
"""
import json
import subprocess
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(HERE, "fincept-qt", "scripts", "paper_trading.py")
DB = "/root/.local/share/fincept/paper_trading.db"
if os.path.exists(DB):
    os.remove(DB)


def call(*args):
    out = subprocess.run([sys.executable, ENGINE, *args], capture_output=True, text=True)
    try:
        return json.loads(out.stdout.strip().splitlines()[-1]) if out.stdout.strip() else {}
    except Exception:
        return {"_raw": out.stdout, "_err": out.stderr}


def quote_frankfurter(pair="USDEUR"):
    """pair like USDEUR -> fetch via frankfurter.dev/v1 (no key, no Qt)."""
    import requests
    base, target = pair[:3], pair[3:]
    r = requests.get(f"https://api.frankfurter.dev/v1/latest?base={base}&symbols={target}", timeout=15)
    r.raise_for_status()
    return float(r.json()["rates"][target])


def quote_yfinance(symbol):
    import yfinance as yf
    t = yf.Ticker(symbol)
    hist = t.history(period="1d")
    return float(hist["Close"].iloc[-1])


def main():
    symbol = sys.argv[1] if len(sys.argv) > 1 else None
    if symbol:
        try:
            price = quote_yfinance(symbol)
            print(f"[market] {symbol} = {price:.2f} (yfinance)")
        except Exception as e:
            print(f"[market] yfinance unavailable ({e}); falling back to USDEUR forex")
            symbol, price = "USDEUR", quote_frankfurter("USDEUR")
            print(f"[market] {symbol} = {price:.4f} (frankfurter)")
    else:
        symbol, price = "USDEUR", quote_frankfurter("USDEUR")
        print(f"[market] {symbol} = {price:.4f} (frankfurter, no API key)")

    p = call("create_portfolio", json.dumps({"name": "live", "balance": 100000}))
    pid = p["id"]
    print(f"[engine] portfolio created id={pid[:8]} balance={p['balance']}")

    o = call("place_order", json.dumps({"portfolio_id": pid, "symbol": symbol,
                                         "side": "buy", "order_type": "market",
                                         "quantity": 1000, "price": price}))
    print(f"[engine] order placed {o['id'][:8]} status={o['status']}")

    fill = call("fill_order", json.dumps({"order_id": o["id"], "price": price}))
    print(f"[engine] filled @ {fill['price']} fee={fill['fee']:.4f} pnl={fill['pnl']}")

    # mark a small move and check stops
    mark = price * 1.001
    call("mark", json.dumps({"portfolio_id": pid, "symbol": symbol, "price": mark}))
    print(f"[engine] marked {symbol} @ {mark:.4f}")

    pos = call("positions", json.dumps({"portfolio_id": pid}))
    print(f"[engine] position: {pos[0]['side']} {pos[0]['quantity']} uPnL={pos[0]['unrealized_pnl']:.4f}")

    # close
    o2 = call("place_order", json.dumps({"portfolio_id": pid, "symbol": symbol,
                                          "side": "sell", "order_type": "market",
                                          "quantity": 1000, "price": mark}))
    call("fill_order", json.dumps({"order_id": o2["id"], "price": mark}))
    stats = call("stats", json.dumps({"portfolio_id": pid}))
    print(f"[engine] closed. realized total_pnl={stats['total_pnl']:.4f} trades={stats['total_trades']} fees={stats['total_fees']:.4f}")
    print("[done] headless paper-trading pipeline verified OK")


if __name__ == "__main__":
    main()
