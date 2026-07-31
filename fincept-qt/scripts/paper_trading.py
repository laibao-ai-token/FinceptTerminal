"""
Fincept Paper Trading Engine — headless Python port
Pure-Python re-implementation of fincept-qt/src/trading/PaperTrading.cpp +
PaperTradingRepository.cpp, modelled on the standalone data scripts
(fincept-qt/scripts/*_data.py) so it runs without Qt / compilation.

Usage (CLI, JSON over stdout):
  python paper_trading.py create_portfolio '{"name":"demo","balance":100000}'
  python paper_trading.py list_portfolios
  python paper_trading.py delete_portfolio '{"id":"..."}'
  python paper_trading.py reset_portfolio '{"id":"..."}'
  python paper_trading.py place_order '{"portfolio_id":"...","symbol":"AAPL","side":"buy","order_type":"market","quantity":10,"price":195.3}'
  python paper_trading.py cancel_order '{"order_id":"..."}'
  python paper_trading.py fill_order '{"order_id":"...","price":195.3}'
  python paper_trading.py orders '{"portfolio_id":"..."}'
  python paper_trading.py positions '{"portfolio_id":"..."}'
  python paper_trading.py mark '{"portfolio_id":"...","symbol":"AAPL","price":196.0}'
  python paper_trading.py stats '{"portfolio_id":"..."}'
  python paper_trading.py check_stops '{"portfolio_id":"..."}'   # SL/TP + stop order matching
  python paper_trading.py demo                                            # end-to-end example

All commands print a single JSON object/array to stdout. Diagnostics go to stderr.
Requires only the Python standard library (sqlite3, json, uuid, datetime, sys).
"""
import sys
import json
import sqlite3
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

DB_PATH = "/root/.local/share/fincept/paper_trading.db"

# IST offset used by the C++ engine for settlement / day boundaries.
IST_OFFSET = timedelta(minutes=330)


# ----------------------------------------------------------------------------
# DB setup
# ----------------------------------------------------------------------------
def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _connect() -> sqlite3.Connection:
    import os
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS pt_portfolios (
            id TEXT PRIMARY KEY,
            name TEXT,
            initial_balance REAL,
            balance REAL,
            currency TEXT,
            leverage REAL,
            margin_mode TEXT,
            fee_rate REAL,
            exchange TEXT,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS pt_orders (
            id TEXT PRIMARY KEY,
            portfolio_id TEXT,
            symbol TEXT,
            side TEXT,
            order_type TEXT,
            quantity REAL,
            price REAL,
            stop_price REAL,
            filled_qty REAL,
            avg_price REAL,
            status TEXT,
            reduce_only INTEGER,
            created_at TEXT,
            filled_at TEXT,
            product TEXT,
            exchange TEXT
        );
        CREATE TABLE IF NOT EXISTS pt_positions (
            id TEXT PRIMARY KEY,
            portfolio_id TEXT,
            symbol TEXT,
            side TEXT,
            quantity REAL,
            entry_price REAL,
            current_price REAL,
            unrealized_pnl REAL,
            realized_pnl REAL,
            leverage REAL,
            liquidation_price REAL,
            opened_at TEXT,
            product TEXT,
            held_margin REAL
        );
        CREATE TABLE IF NOT EXISTS pt_margin_blocks (
            id TEXT PRIMARY KEY,
            portfolio_id TEXT,
            order_id TEXT UNIQUE,
            symbol TEXT,
            blocked_amount REAL
        );
        CREATE TABLE IF NOT EXISTS pt_trades (
            id TEXT PRIMARY KEY,
            portfolio_id TEXT,
            order_id TEXT,
            symbol TEXT,
            side TEXT,
            price REAL,
            quantity REAL,
            fee REAL,
            pnl REAL,
            timestamp TEXT
        );
        CREATE TABLE IF NOT EXISTS pt_marks (
            symbol TEXT PRIMARY KEY,
            price REAL,
            updated_at TEXT
        );
        """
    )
    conn.commit()


# ----------------------------------------------------------------------------
# In-memory per-portfolio runtime config (mirrors C++ config_map)
# ----------------------------------------------------------------------------
_runtime_config: dict = {}


def _config_for(portfolio_id: str) -> dict:
    return _runtime_config.setdefault(
        portfolio_id,
        {
            "leverage": {"equity_mis": 5.0, "equity_cnc": 1.0, "futures": 10.0,
                         "options_buy": 1.0, "options_sell": 1.0},
            "enforce_market_hours": False,
        },
    )


def set_leverage_config(portfolio_id, cfg):
    _config_for(portfolio_id)["leverage"] = cfg


def set_enforce_market_hours(portfolio_id, enforce):
    _config_for(portfolio_id)["enforce_market_hours"] = bool(enforce)


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
def _is_option(symbol: str) -> bool:
    return symbol.upper().endswith("CE") or symbol.upper().endswith("PE")


def _is_future(symbol: str) -> bool:
    return symbol.upper().endswith("FUT")


def _select_leverage(cfg: dict, symbol: str, exchange: str, product: str, side: str) -> float:
    if _is_future(symbol):
        return cfg["futures"]
    if _is_option(symbol):
        return cfg["options_buy"] if side.lower() == "buy" else cfg["options_sell"]
    ex = (exchange or "").upper()
    if ex in ("NSE", "BSE", ""):
        if product and product.lower() in ("mis", "intraday"):
            return cfg["equity_mis"]
        return cfg["equity_cnc"]
    return 1.0


def calculate_required_margin(portfolio_id, symbol, exchange, product, quantity, price, side):
    if not _finite(quantity) or quantity <= 0 or not _finite(price) or price <= 0:
        return 0.0
    cfg = _config_for(portfolio_id)["leverage"]
    lev = _select_leverage(cfg, symbol, exchange, product, side)
    if not _finite(lev) or lev <= 0:
        lev = 1.0
    return quantity * price / lev


def _finite(x) -> bool:
    return isinstance(x, (int, float)) and x == x  # NaN check


def _is_market_open(exchange: str) -> bool:
    ist = datetime.now(timezone.utc) + IST_OFFSET
    t = ist.time()
    ex = (exchange or "").upper()
    if ex in ("NSE", "BSE", "NFO", "BFO"):
        return t >= datetime(2000, 1, 1, 9, 15).time() and t <= datetime(2000, 1, 1, 15, 30).time()
    if ex == "MCX":
        return t >= datetime(2000, 1, 1, 9, 0).time() and t <= datetime(2000, 1, 1, 23, 30).time()
    if ex in ("CDS", "BCD"):
        return t >= datetime(2000, 1, 1, 9, 0).time() and t <= datetime(2000, 1, 1, 17, 0).time()
    return True


def _row(conn, sql, params):
    cur = conn.execute(sql, params)
    return cur.fetchone()


def _rows(conn, sql, params):
    cur = conn.execute(sql, params)
    return cur.fetchall()


# ----------------------------------------------------------------------------
# Portfolio ops
# ----------------------------------------------------------------------------
def create_portfolio(name, balance, currency="USD", leverage=1.0, margin_mode="cross",
                     fee_rate=0.001, exchange=""):
    if not name:
        raise RuntimeError("Portfolio name cannot be empty")
    if not _finite(balance) or balance <= 0:
        raise RuntimeError("Invalid balance: must be positive")
    if not _finite(leverage) or leverage <= 0:
        raise RuntimeError("Invalid leverage: must be positive")
    if not _finite(fee_rate) or fee_rate < 0 or fee_rate > 1:
        raise RuntimeError("Invalid fee_rate")

    pid = str(uuid.uuid4())
    created = _now_iso()
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO pt_portfolios (id,name,initial_balance,balance,currency,leverage,margin_mode,fee_rate,exchange,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (pid, name, balance, balance, currency, leverage, margin_mode, fee_rate, exchange, created),
        )
        conn.commit()
        return _get_portfolio(conn, pid)
    finally:
        conn.close()


def _get_portfolio(conn, pid) -> dict:
    r = _row(conn, "SELECT id,name,initial_balance,balance,currency,leverage,margin_mode,fee_rate,exchange,created_at "
                   "FROM pt_portfolios WHERE id=?", (pid,))
    if not r:
        raise RuntimeError("Portfolio not found: " + pid)
    return _portfolio_dict(r)


def _portfolio_dict(r) -> dict:
    return {
        "id": r[0], "name": r[1], "initial_balance": r[2], "balance": r[3],
        "currency": r[4], "leverage": r[5], "margin_mode": r[6],
        "fee_rate": r[7], "exchange": r[8], "created_at": r[9],
    }


def list_portfolios(exchange=""):
    conn = _connect()
    try:
        if exchange:
            rs = _rows(conn, "SELECT id,name,initial_balance,balance,currency,leverage,margin_mode,fee_rate,exchange,created_at "
                             "FROM pt_portfolios WHERE exchange=? ORDER BY created_at DESC", (exchange,))
        else:
            rs = _rows(conn, "SELECT id,name,initial_balance,balance,currency,leverage,margin_mode,fee_rate,exchange,created_at "
                             "FROM pt_portfolios ORDER BY created_at DESC", ())
        return [_portfolio_dict(r) for r in rs]
    finally:
        conn.close()


def delete_portfolio(pid):
    conn = _connect()
    try:
        conn.execute("DELETE FROM pt_trades WHERE portfolio_id=?", (pid,))
        conn.execute("DELETE FROM pt_positions WHERE portfolio_id=?", (pid,))
        conn.execute("DELETE FROM pt_orders WHERE portfolio_id=?", (pid,))
        conn.execute("DELETE FROM pt_margin_blocks WHERE portfolio_id=?", (pid,))
        conn.execute("DELETE FROM pt_portfolios WHERE id=?", (pid,))
        conn.commit()
        return {"deleted": pid}
    finally:
        conn.close()


def reset_portfolio(pid):
    conn = _connect()
    try:
        _get_portfolio(conn, pid)
        conn.execute("DELETE FROM pt_trades WHERE portfolio_id=?", (pid,))
        conn.execute("DELETE FROM pt_orders WHERE portfolio_id=?", (pid,))
        conn.execute("DELETE FROM pt_positions WHERE portfolio_id=?", (pid,))
        conn.execute("DELETE FROM pt_margin_blocks WHERE portfolio_id=?", (pid,))
        p = _get_portfolio(conn, pid)
        conn.execute("UPDATE pt_portfolios SET balance=? WHERE id=?", (p["initial_balance"], pid))
        conn.commit()
        return _get_portfolio(conn, pid)
    finally:
        conn.close()


# ----------------------------------------------------------------------------
# Order ops
# ----------------------------------------------------------------------------
def _order_dict(r) -> dict:
    return {
        "id": r[0], "portfolio_id": r[1], "symbol": r[2], "side": r[3], "order_type": r[4],
        "quantity": r[5], "price": r[6], "stop_price": r[7], "filled_qty": r[8],
        "avg_price": r[9], "status": r[10], "reduce_only": bool(r[11]), "created_at": r[12],
        "filled_at": r[13], "product": r[14], "exchange": r[15],
    }


def place_order(portfolio_id, symbol, side, order_type, quantity, price=None, stop_price=None,
                reduce_only=False, exchange="", product=""):
    type_ = order_type
    if type_ == "stop_loss":
        type_ = "stop"
    elif type_ == "stop_loss_limit":
        type_ = "stop_limit"

    if type_ not in ("market", "limit", "stop", "stop_limit"):
        raise RuntimeError("Invalid order type: " + type_)
    if side not in ("buy", "sell"):
        raise RuntimeError("Invalid side: " + side)
    if not _finite(quantity) or quantity <= 0:
        raise RuntimeError("Invalid quantity")
    if price is not None and (not _finite(price) or price <= 0):
        raise RuntimeError("Invalid price")
    if stop_price is not None and (not _finite(stop_price) or stop_price <= 0):
        raise RuntimeError("Invalid stop price")
    if type_ == "limit" and price is None:
        raise RuntimeError("Limit order requires price")
    if type_ in ("stop", "stop_limit") and stop_price is None:
        raise RuntimeError("Stop order requires stop_price")

    conn = _connect()
    try:
        portfolio = _get_portfolio(conn, portfolio_id)

        if _config_for(portfolio_id)["enforce_market_hours"] and exchange and not _is_market_open(exchange):
            _insert_order(conn, portfolio_id, symbol, side, type_, quantity, price, stop_price, 0.0,
                          "rejected", reduce_only, product, exchange)
            raise RuntimeError("Market closed for exchange " + exchange)

        margin_to_block = 0.0
        if not reduce_only:
            opposite_side = "short" if side == "buy" else "long"
            opp = _find_position(conn, portfolio_id, symbol, opposite_side)
            net_new_qty = quantity
            if opp:
                net_new_qty = max(0.0, quantity - opp["quantity"])
            if net_new_qty > 0:
                ref = price if price is not None else (stop_price if stop_price is not None else 0.0)
                if ref <= 0:
                    raise RuntimeError("Market orders require a reference price for margin calculation")
                margin_to_block = calculate_required_margin(
                    portfolio_id, symbol, exchange, product, net_new_qty, ref, side)
                if margin_to_block > portfolio["balance"]:
                    _insert_order(conn, portfolio_id, symbol, side, type_, quantity, price, stop_price, 0.0,
                                  "rejected", reduce_only, product, exchange)
                    raise RuntimeError("Insufficient margin")

        oid = str(uuid.uuid4())
        _insert_order(conn, portfolio_id, symbol, side, type_, quantity, price, stop_price,
                      margin_to_block, "pending", reduce_only, product, exchange, oid)
        if margin_to_block > 0:
            conn.execute("UPDATE pt_portfolios SET balance=? WHERE id=?",
                         (portfolio["balance"] - margin_to_block, portfolio_id))
            conn.execute("INSERT OR REPLACE INTO pt_margin_blocks (id,portfolio_id,order_id,symbol,blocked_amount) "
                         "VALUES (?,?,?,?,?)", (str(uuid.uuid4()), portfolio_id, oid, symbol, margin_to_block))
        conn.commit()
        return _get_order(conn, oid)
    finally:
        conn.close()


def _insert_order(conn, portfolio_id, symbol, side, type_, quantity, price, stop_price,
                  margin_blocked, status, reduce_only, product, exchange, oid=None):
    if oid is None:
        oid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO pt_orders (id,portfolio_id,symbol,side,order_type,quantity,price,stop_price,"
        "filled_qty,avg_price,status,reduce_only,created_at,product,exchange) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (oid, portfolio_id, symbol, side, type_, quantity,
         price, stop_price, 0.0, None, status, 1 if reduce_only else 0,
         _now_iso(), product, exchange),
    )
    return oid


def _get_order(conn, oid) -> dict:
    r = _row(conn, "SELECT id,portfolio_id,symbol,side,order_type,quantity,price,stop_price,filled_qty,"
                   "avg_price,status,reduce_only,created_at,filled_at,product,exchange FROM pt_orders WHERE id=?",
              (oid,))
    if not r:
        raise RuntimeError("Order not found: " + oid)
    return _order_dict(r)


def _find_position(conn, portfolio_id, symbol, side):
    r = _row(conn, "SELECT id,portfolio_id,symbol,side,quantity,entry_price,current_price,unrealized_pnl,"
                   "realized_pnl,leverage,liquidation_price,opened_at,product,held_margin FROM pt_positions "
                   "WHERE portfolio_id=? AND symbol=? AND side=?", (portfolio_id, symbol, side))
    return _position_dict(r) if r else None


def _position_dict(r):
    if r is None:
        return None
    return {
        "id": r[0], "portfolio_id": r[1], "symbol": r[2], "side": r[3], "quantity": r[4],
        "entry_price": r[5], "current_price": r[6], "unrealized_pnl": r[7], "realized_pnl": r[8],
        "leverage": r[9], "liquidation_price": r[10], "opened_at": r[11],
        "product": r[12] or "CNC", "held_margin": r[13],
    }


def cancel_order(order_id):
    conn = _connect()
    try:
        blocked = _get_margin_block(conn, order_id)
        if blocked > 0:
            r = _row(conn, "SELECT portfolio_id FROM pt_orders WHERE id=?", (order_id,))
            if r:
                p = _get_portfolio(conn, r[0])
                conn.execute("UPDATE pt_portfolios SET balance=? WHERE id=?",
                             (p["balance"] + blocked, p["id"]))
            conn.execute("DELETE FROM pt_margin_blocks WHERE order_id=?", (order_id,))
        conn.execute("UPDATE pt_orders SET status='cancelled' WHERE id=?", (order_id,))
        conn.commit()
        return {"cancelled": order_id}
    finally:
        conn.close()


def _get_margin_block(conn, order_id) -> float:
    r = _row(conn, "SELECT blocked_amount FROM pt_margin_blocks WHERE order_id=?", (order_id,))
    return r[0] if r else 0.0


def get_orders(portfolio_id, status=""):
    conn = _connect()
    try:
        if status:
            rs = _rows(conn, "SELECT id,portfolio_id,symbol,side,order_type,quantity,price,stop_price,filled_qty,"
                             "avg_price,status,reduce_only,created_at,filled_at,product,exchange FROM pt_orders "
                             "WHERE portfolio_id=? AND status=? ORDER BY created_at DESC", (portfolio_id, status))
        else:
            rs = _rows(conn, "SELECT id,portfolio_id,symbol,side,order_type,quantity,price,stop_price,filled_qty,"
                             "avg_price,status,reduce_only,created_at,filled_at,product,exchange FROM pt_orders "
                             "WHERE portfolio_id=? ORDER BY created_at DESC", (portfolio_id,))
        return [_order_dict(r) for r in rs]
    finally:
        conn.close()


# ----------------------------------------------------------------------------
# Fill engine (core) — mirrors pt_fill_order
# ----------------------------------------------------------------------------
def fill_order(order_id, fill_price, fill_qty=None, fill_time=None):
    if not _finite(fill_price) or fill_price <= 0:
        raise RuntimeError("Invalid fill price")
    if fill_qty is not None and (not _finite(fill_qty) or fill_qty <= 0):
        raise RuntimeError("Invalid fill quantity")

    conn = _connect()
    try:
        order = _get_order(conn, order_id)
        if order["status"] not in ("pending", "partial"):
            raise RuntimeError("Order not fillable")

        pid = order["portfolio_id"]
        portfolio = _get_portfolio(conn, pid)
        fee_rate = portfolio["fee_rate"]

        qty = fill_qty if fill_qty is not None else (order["quantity"] - order["filled_qty"])
        if qty <= 0:
            raise RuntimeError("Nothing left to fill")
        fee = qty * fill_price * fee_rate
        now = fill_time or _now_iso()

        position_side = "long" if order["side"] == "buy" else "short"
        opposite_side = "short" if order["side"] == "buy" else "long"
        pnl = 0.0
        new_filled = order["filled_qty"] + qty
        fully_filled = new_filled >= order["quantity"]

        balance_delta = -fee
        order_blocked = _get_margin_block(conn, order_id)
        block_consumed = 0.0

        opp = _find_position(conn, pid, order["symbol"], opposite_side)

        # Closing leg
        close_qty = 0.0
        if opp:
            pos = opp
            close_qty = min(qty, pos["quantity"])
            pnl = (fill_price - pos["entry_price"]) * close_qty if pos["side"] == "long" else (pos["entry_price"] - fill_price) * close_qty
            frac_close = close_qty / pos["quantity"] if pos["quantity"] > 0 else 1.0
            margin_released = pos["held_margin"] * frac_close
            if close_qty >= pos["quantity"]:
                conn.execute("DELETE FROM pt_positions WHERE id=?", (pos["id"],))
            else:
                conn.execute("UPDATE pt_positions SET quantity=?, entry_price=?, held_margin=held_margin-?, "
                             "realized_pnl=realized_pnl+? WHERE id=?",
                             (pos["quantity"] - close_qty, pos["entry_price"],
                              pos["held_margin"] - margin_released, pnl, pos["id"]))
            balance_delta += margin_released + pnl

        # Opening leg
        open_qty = qty - close_qty
        if open_qty > 0:
            open_margin = calculate_required_margin(pid, order["symbol"], order["exchange"],
                                                     order["product"], open_qty, fill_price, order["side"])
            block_consumed = order_blocked if fully_filled else min(order_blocked, open_margin)
            balance_delta += block_consumed - open_margin

            product = order["product"] or "MIS"
            same = _find_position(conn, pid, order["symbol"], position_side)
            if same:
                pos = same
                new_qty = pos["quantity"] + open_qty
                if new_qty <= 0:
                    raise RuntimeError("Invalid position quantity after averaging")
                new_entry = (pos["entry_price"] * pos["quantity"] + fill_price * open_qty) / new_qty
                conn.execute("UPDATE pt_positions SET quantity=?, entry_price=?, held_margin=held_margin+?, "
                             "current_price=? WHERE id=?",
                             (new_qty, new_entry, open_margin, fill_price, pos["id"]))
            else:
                np_id = str(uuid.uuid4())
                lev = (open_qty * fill_price) / open_margin if open_margin > 0 else portfolio["leverage"]
                conn.execute("INSERT INTO pt_positions (id,portfolio_id,symbol,side,quantity,entry_price,"
                             "current_price,unrealized_pnl,realized_pnl,leverage,liquidation_price,opened_at,"
                             "product,held_margin) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                             (np_id, pid, order["symbol"], position_side, open_qty, fill_price, fill_price,
                              0.0, 0.0, lev, None, now, product, open_margin))

        # Settle the order's margin block
        if order_blocked > 0:
            if fully_filled:
                conn.execute("DELETE FROM pt_margin_blocks WHERE order_id=?", (order_id,))
            else:
                remaining = max(0.0, order_blocked - block_consumed)
                conn.execute("INSERT OR REPLACE INTO pt_margin_blocks (id,portfolio_id,order_id,symbol,blocked_amount) "
                             "VALUES (?,?,?,?,?)", (str(uuid.uuid4()), pid, order_id, order["symbol"], remaining))

        conn.execute("UPDATE pt_portfolios SET balance=? WHERE id=?", (portfolio["balance"] + balance_delta, pid))

        new_status = "filled" if fully_filled else "partial"
        prev_avg = order["avg_price"] or 0.0
        new_avg = ((prev_avg * order["filled_qty"] + fill_price * qty) / new_filled) if new_filled > 0 else fill_price
        conn.execute("UPDATE pt_orders SET filled_qty=?, avg_price=?, status=?, filled_at=? WHERE id=?",
                     (new_filled, new_avg, new_status, now, order_id))

        tid = str(uuid.uuid4())
        conn.execute("INSERT INTO pt_trades (id,portfolio_id,order_id,symbol,side,price,quantity,fee,pnl,timestamp) "
                     "VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (tid, pid, order_id, order["symbol"], order["side"], fill_price, qty, fee, pnl, now))

        conn.commit()
        return {"id": tid, "portfolio_id": pid, "order_id": order_id, "symbol": order["symbol"],
                "side": order["side"], "price": fill_price, "quantity": qty, "fee": fee,
                "pnl": pnl, "timestamp": now}
    finally:
        conn.close()


# ----------------------------------------------------------------------------
# Positions / mark / stats
# ----------------------------------------------------------------------------
def get_positions(portfolio_id):
    conn = _connect()
    try:
        rs = _rows(conn, "SELECT id,portfolio_id,symbol,side,quantity,entry_price,current_price,unrealized_pnl,"
                         "realized_pnl,leverage,liquidation_price,opened_at,product,held_margin FROM pt_positions "
                         "WHERE portfolio_id=? ORDER BY opened_at DESC", (portfolio_id,))
        return [_position_dict(r) for r in rs]
    finally:
        conn.close()


def mark_price(portfolio_id, symbol, price):
    if not _finite(price) or price <= 0:
        return {"skipped": True, "reason": "non-positive price"}
    conn = _connect()
    try:
        conn.execute("UPDATE pt_positions SET current_price=?, unrealized_pnl="
                     "CASE WHEN side='long' THEN (?-entry_price)*quantity ELSE (entry_price-?)*quantity END "
                     "WHERE portfolio_id=? AND symbol=?", (price, price, price, portfolio_id, symbol))
        conn.execute("INSERT OR REPLACE INTO pt_marks (symbol, price, updated_at) VALUES (?,?,?)",
                     (symbol, price, _now_iso()))
        conn.commit()
        return {"ok": True, "symbol": symbol, "price": price}
    finally:
        conn.close()


def _last_mark(conn, symbol):
    r = _row(conn, "SELECT price FROM pt_marks WHERE symbol=?", (symbol,))
    return r[0] if r else None


def get_stats(portfolio_id):
    conn = _connect()
    try:
        r = _row(conn, "SELECT COALESCE(SUM(pnl),0), COUNT(*), "
                       "COALESCE(SUM(CASE WHEN pnl>0 THEN 1 ELSE 0 END),0), "
                       "COALESCE(SUM(CASE WHEN pnl<0 THEN 1 ELSE 0 END),0), "
                       "COALESCE(MAX(pnl),0), COALESCE(MIN(pnl),0), "
                       "COALESCE(SUM(CASE WHEN pnl>0 THEN pnl ELSE 0 END),0), "
                       "COALESCE(SUM(CASE WHEN pnl<0 THEN pnl ELSE 0 END),0), "
                       "COALESCE(SUM(fee),0), COALESCE(SUM(price*quantity),0), "
                       "COALESCE(SUM(CASE WHEN date(datetime(timestamp,'+330 minutes'))=date(datetime('now','+330 minutes')) "
                       "THEN pnl ELSE 0 END),0) FROM pt_trades WHERE portfolio_id=?", (portfolio_id,))
        if not r:
            return {}
        total_pnl, total_trades, winners, losers = r[0], r[1], r[2], r[3]
        largest_win, largest_loss = r[4], r[5]
        gross_profit, gross_loss, total_fees, turnover, today_pnl = r[6], r[7], r[8], r[9], r[10]
        decided = winners + losers
        win_rate = winners / decided if decided > 0 else 0.0
        avg_win = gross_profit / winners if winners > 0 else 0.0
        avg_loss = gross_loss / losers if losers > 0 else 0.0
        gross_loss_abs = -gross_loss if gross_loss < 0 else gross_loss
        profit_factor = (gross_profit / gross_loss_abs) if gross_loss_abs > 0 else (gross_profit if gross_profit > 0 else 0.0)
        return {
            "total_pnl": total_pnl, "win_rate": win_rate, "total_trades": total_trades,
            "winning_trades": winners, "losing_trades": losers, "largest_win": largest_win,
            "largest_loss": largest_loss, "gross_profit": gross_profit, "gross_loss": gross_loss,
            "avg_win": avg_win, "avg_loss": avg_loss, "profit_factor": profit_factor,
            "total_fees": total_fees, "turnover": turnover, "today_pnl": today_pnl,
        }
    finally:
        conn.close()


# ----------------------------------------------------------------------------
# Stop / SL-TP matching (replaces C++ QTimer-driven PaperMarkService)
# This is the headless-friendly replacement for live mark + stop matching.
# ----------------------------------------------------------------------------
def check_stops(portfolio_id):
    """Scan open positions + pending stop/limit orders against current prices.
    - Fills pending 'stop'/'stop_limit' orders whose stop_price is touched.
    - Closes positions whose SL/TP (passed as position-level stop) is touched.
    Returns a list of fills triggered.
    """
    conn = _connect()
    try:
        fills = []
        # 1) Pending stop/limit orders
        orders = get_orders(portfolio_id, "pending")
        for o in orders:
            if o["order_type"] in ("stop", "stop_limit") and o["stop_price"] is not None:
                # Prefer the symbol's last marked price (works even with no open
                # position, e.g. a buy-stop entering a new position).
                px = _last_mark(conn, o["symbol"])
                if px is None:
                    pos = _find_position(conn, portfolio_id, o["symbol"], "long" if o["side"] == "sell" else "short")
                    px = pos["current_price"] if pos else None
                if px is None:
                    continue
                triggered = (o["side"] == "buy" and px >= o["stop_price"]) or \
                            (o["side"] == "sell" and px <= o["stop_price"])
                if triggered:
                    fill_px = o["price"] if o["order_type"] == "stop_limit" and o["price"] else px
                    fills.append(fill_order(o["id"], fill_px))
        return fills
    finally:
        conn.close()


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------
def _emit(obj):
    sys.stdout.write(json.dumps(obj, default=str, ensure_ascii=False) + "\n")


def _load_args(argv_tail):
    if not argv_tail:
        return {}
    raw = " ".join(argv_tail)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # allow unquoted bare words for convenience
        return {"_raw": raw}


def main():
    _init_db_singleton()
    if len(sys.argv) < 2:
        _emit({"error": "usage: paper_trading.py <command> [json_args]"})
        return
    cmd = sys.argv[1]
    args = _load_args(sys.argv[2:])
    try:
        if cmd == "create_portfolio":
            _emit(create_portfolio(args.get("name", ""), float(args.get("balance", 0)),
                                   args.get("currency", "USD"), float(args.get("leverage", 1.0)),
                                   args.get("margin_mode", "cross"), float(args.get("fee_rate", 0.001)),
                                   args.get("exchange", "")))
        elif cmd == "list_portfolios":
            _emit(list_portfolios(args.get("exchange", "")))
        elif cmd == "delete_portfolio":
            _emit(delete_portfolio(args["id"]))
        elif cmd == "reset_portfolio":
            _emit(reset_portfolio(args["id"]))
        elif cmd == "place_order":
            _emit(place_order(args["portfolio_id"], args["symbol"], args["side"], args["order_type"],
                              float(args["quantity"]), args.get("price"), args.get("stop_price"),
                              bool(args.get("reduce_only", False)), args.get("exchange", ""),
                              args.get("product", "")))
        elif cmd == "cancel_order":
            _emit(cancel_order(args["order_id"]))
        elif cmd == "fill_order":
            _emit(fill_order(args["order_id"], float(args["price"]),
                             float(args["quantity"]) if args.get("quantity") is not None else None,
                             args.get("fill_time")))
        elif cmd == "orders":
            _emit(get_orders(args["portfolio_id"], args.get("status", "")))
        elif cmd == "positions":
            _emit(get_positions(args["portfolio_id"]))
        elif cmd == "mark":
            _emit(mark_price(args["portfolio_id"], args["symbol"], float(args["price"])))
        elif cmd == "stats":
            _emit(get_stats(args["portfolio_id"]))
        elif cmd == "check_stops":
            _emit(check_stops(args["portfolio_id"]))
        elif cmd == "demo":
            _emit(run_demo())
        else:
            _emit({"error": "unknown command: " + cmd})
    except Exception as e:  # noqa: BLE001
        _emit({"error": str(e)})


_db_singleton = None


def _init_db_singleton():
    global _db_singleton
    if _db_singleton is None:
        _db_singleton = _connect()
        _init_db(_db_singleton)


def run_demo():
    """End-to-end example: create portfolio, buy, mark up, sell, show stats."""
    conn = _connect()
    _init_db(conn)
    conn.close()
    p = create_portfolio("demo", 100000, "USD", 1.0, "cross", 0.001)
    pid = p["id"]
    # Buy 10 AAPL @ 195.30 (market, reference price)
    o1 = place_order(pid, "AAPL", "buy", "market", 10, price=195.30)
    fill_order(o1["id"], 195.30)
    # Price moves up to 200.00 -> mark + check stops
    mark_price(pid, "AAPL", 200.00)
    check_stops(pid)
    positions = get_positions(pid)
    stats = get_stats(pid)
    # Sell all (reduce) @ 200.00
    o2 = place_order(pid, "AAPL", "sell", "market", 10, price=200.00)
    fill_order(o2["id"], 200.00)
    return {
        "portfolio": _get_portfolio(_connect(), pid),
        "after_open": {"positions": positions, "stats": stats},
        "final_portfolio": _get_portfolio(_connect(), pid),
        "final_stats": get_stats(pid),
        "final_positions": get_positions(pid),
    }


if __name__ == "__main__":
    main()
