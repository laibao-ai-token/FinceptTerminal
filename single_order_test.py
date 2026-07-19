"""
Single-order (单词/单笔) test: exercise individual engine commands one by one
and verify each returns sane JSON. Mirrors how the standalone data scripts are
smoke-tested. Covers: create, place (limit + market), mark, check_stops,
fill (full + partial), stats, orders, positions, cancel, reset, delete.

Usage:
  source .venv-pt/bin/activate
  python single_order_test.py
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

PASS, FAIL = 0, 0


def call(*args):
    global PASS, FAIL
    out = subprocess.run([sys.executable, ENGINE, *args], capture_output=True, text=True)
    last = out.stdout.strip().splitlines()[-1] if out.stdout.strip() else "{}"
    try:
        obj = json.loads(last)
    except Exception:
        obj = {"_raw": out.stdout, "_err": out.stderr}
    ok = "error" not in obj
    print(("  PASS " if ok else "  FAIL ") + " ".join(args) +
          ("" if ok else "  -> " + str(obj.get("error", obj))))
    if ok:
        PASS += 1
    else:
        FAIL += 1
    return obj


def main():
    print("== single-order smoke test ==")
    p = call("create_portfolio", json.dumps({"name": "t", "balance": 50000, "fee_rate": 0.001}))
    pid = p["id"]

    # 1) limit order (no immediate fill)
    o1 = call("place_order", json.dumps({"portfolio_id": pid, "symbol": "BTC", "side": "buy",
                                          "order_type": "limit", "quantity": 0.5, "price": 60000,
                                          "exchange": "BINANCE"}))
    assert o1["status"] == "pending", o1

    # 2) mark price, run stop checker (limit untouched since price not at limit)
    call("mark", json.dumps({"portfolio_id": pid, "symbol": "BTC", "price": 60100}))
    call("check_stops", json.dumps({"portfolio_id": pid}))

    # 3) partial fill of the limit order
    f1 = call("fill_order", json.dumps({"order_id": o1["id"], "price": 60000, "quantity": 0.2}))
    assert f1["pnl"] == 0.0, f1
    o1b = call("orders", json.dumps({"portfolio_id": pid, "status": "partial"}))
    assert o1b[0]["filled_qty"] == 0.2, o1b

    # 4) remaining fill
    call("fill_order", json.dumps({"order_id": o1["id"], "price": 60000}))

    # 5) stop order that should trigger on mark.
    #    We hold a LONG BTC position. A protective SELL-stop fires when price
    #    FALLS to/below the stop. Mark price DOWN to 59800 (below the 60100 stop)
    #    so the sell-stop triggers (realistic protective-stop scenario).
    call("mark", json.dumps({"portfolio_id": pid, "symbol": "BTC", "price": 59800}))
    o2 = call("place_order", json.dumps({"portfolio_id": pid, "symbol": "BTC", "side": "sell",
                                          "order_type": "stop", "quantity": 0.5, "stop_price": 60100}))
    triggered = call("check_stops", json.dumps({"portfolio_id": pid}))
    assert len(triggered) >= 1, triggered
    print(f"  info  stop triggered fills: {len(triggered)}")

    # 5b) a BUY-stop that fires when price RISES to the stop (mark back up)
    call("mark", json.dumps({"portfolio_id": pid, "symbol": "BTC", "price": 61000}))
    o3 = call("place_order", json.dumps({"portfolio_id": pid, "symbol": "BTC", "side": "buy",
                                          "order_type": "stop", "quantity": 0.1, "stop_price": 60500}))
    triggered2 = call("check_stops", json.dumps({"portfolio_id": pid}))
    assert len(triggered2) >= 1, triggered2
    print(f"  info  buy-stop triggered fills: {len(triggered2)}")

    # 6) positions + stats
    pos = call("positions", json.dumps({"portfolio_id": pid}))
    st = call("stats", json.dumps({"portfolio_id": pid}))
    print(f"  info  positions={len(pos)} total_pnl={st['total_pnl']:.4f} trades={st['total_trades']}")

    # 7) cancel a fresh pending order
    o4 = call("place_order", json.dumps({"portfolio_id": pid, "symbol": "ETH", "side": "buy",
                                          "order_type": "limit", "quantity": 1, "price": 3000}))
    call("cancel_order", json.dumps({"order_id": o4["id"]}))

    # 8) reset + delete
    call("reset_portfolio", json.dumps({"id": pid}))
    call("delete_portfolio", json.dumps({"id": pid}))

    print(f"== result: {PASS} passed, {FAIL} failed ==")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
