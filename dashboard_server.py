"""dashboard_server.py — 资金盘面展示服务（轻量，读 paper_trading.db + yfinance 行情）"""
import sqlite3
from datetime import datetime, timedelta

import yfinance as yf
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

DB = "/root/.local/share/fincept/paper_trading.db"
PORTFOLIO_ID = "a315ec90-ed54-4c2e-8107-5789482885e9"  # 真实资金-30万
DEFAULT_IDS = [PORTFOLIO_ID]  # 如无此组合则回退全部

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"])


def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def resolve_pids(pids):
    con = db()
    ids = [r["id"] for r in con.execute("SELECT id FROM pt_portfolios ORDER BY created_at")]
    if pids:
        ids = [p for p in pids if p in ids]
    return ids


def hk_or_cn_suffix(symbol: str) -> str:
    s = symbol.upper()
    if s.endswith(".HK") or s.endswith(".SS") or s.endswith(".SZ"):
        return s
    if s.isdigit() and len(s) == 4:
        return s + ".HK"
    if s.isdigit():
        return s + ".SS"
    return s


@app.get("/api/portfolios")
def portfolios():
    con = db()
    rows = con.execute("SELECT id, name, balance, initial_balance, currency FROM pt_portfolios ORDER BY created_at").fetchall()
    return [dict(r) for r in rows]


@app.get("/api/overview")
def overview(pids: str = None):
    con = db()
    ids = resolve_pids(pids.split(",") if pids else None)
    out = []
    for pid in ids:
        p = con.execute("SELECT * FROM pt_portfolios WHERE id=?", (pid,)).fetchone()
        positions = con.execute("SELECT * FROM pt_positions WHERE portfolio_id=?", (pid,)).fetchall()
        mkt = 0.0
        for pos in positions:
            price = pos["current_price"] or pos["entry_price"] or 0
            mkt += pos["quantity"] * price
        t = con.execute("SELECT COALESCE(SUM(fee),0) f, COALESCE(SUM(pnl),0) p FROM pt_trades WHERE portfolio_id=?", (pid,)).fetchone()
        out.append({
            "id": pid, "name": p["name"], "cash": p["balance"],
            "initial": p["initial_balance"], "currency": p["currency"],
            "market_value": round(mkt, 2), "total_assets": round(p["balance"] + mkt, 2),
            "positions": len(positions), "total_fees": round(t["f"], 2), "realized_pnl": round(t["p"], 2),
        })
    return out


@app.get("/api/positions")
def positions(pids: str = None):
    con = db()
    ids = resolve_pids(pids.split(",") if pids else None)
    rows = con.execute(f"SELECT * FROM pt_positions WHERE portfolio_id IN ({','.join('?'*len(ids))})", ids).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/cashflow")
def cashflow(days: int = 90):
    con = db()
    since = (datetime.utcnow() - timedelta(days=days)).isoformat()
    rows = con.execute(
        """SELECT date(timestamp) d,
                  SUM(CASE WHEN side='buy' THEN price*quantity END) buy,
                  SUM(CASE WHEN side='sell' THEN price*quantity END) sell,
                  SUM(fee) fee
           FROM pt_trades WHERE timestamp >= ? GROUP BY d ORDER BY d""", (since,)).fetchall()
    cash, net = 0.0, 0.0
    out = []
    for r in rows:
        buy = r["buy"] or 0
        sell = r["sell"] or 0
        cash -= buy + r["fee"]
        cash += sell - r["fee"]
        net += sell - buy - r["fee"]
        out.append({"date": r["d"], "buy": round(buy, 2), "sell": round(sell, 2),
                    "fee": round(r["fee"], 2), "net": round(net, 2)})
    return out


@app.get("/api/trades")
def trades(limit: int = 100):
    con = db()
    rows = con.execute(
        "SELECT t.*, p.name pname FROM pt_trades t JOIN pt_portfolios p ON p.id=t.portfolio_id "
        "ORDER BY t.timestamp DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/orders")
def orders(limit: int = 100):
    con = db()
    rows = con.execute(
        "SELECT o.*, p.name pname FROM pt_orders o JOIN pt_portfolios p ON p.id=o.portfolio_id "
        "ORDER BY o.created_at DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/refresh")
def refresh():
    con = db()
    syms = [r["symbol"] for r in con.execute("SELECT DISTINCT symbol FROM pt_positions")]
    marks = 0
    for s in syms:
        try:
            t = yf.Ticker(hk_or_cn_suffix(s))
            price = t.fast_info.last_price
            if price:
                con.execute("INSERT INTO pt_marks(symbol, price, updated_at) VALUES(?,?,?) "
                            "ON CONFLICT(symbol) DO UPDATE SET price=?, updated_at=?",
                            (s, price, datetime.utcnow().isoformat(), price, datetime.utcnow().isoformat()))
                con.execute("UPDATE pt_positions SET current_price=? WHERE symbol=?", (price, s))
                marks += 1
        except Exception as e:
            print(f"refresh {s}: {e}")
    con.commit()
    return {"refreshed": marks, "symbols": syms}


@app.get("/", response_class=HTMLResponse)
def index():
    return open("dashboard.html", encoding="utf-8").read()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8898)
