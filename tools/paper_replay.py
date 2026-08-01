#!/usr/bin/env python3
"""模拟盘引擎回测（订单级回放）— 用 paper_trading 引擎逐日执行策略信号。

与 bt numpy fallback（仅仓位开关）不同，这里每次信号都真实下单：
金叉→paper_buy、死叉→paper_sell，用当日收盘价成交，带手续费/持仓/订单级统计。

用法: python paper_replay.py 1810.HK sma_crossover 2026-02-01 2026-08-01
"""
import sys, os, json
from datetime import datetime

os.environ["PYTHONPATH"] = "/root/workspace/FinceptTerminal"
sys.path.insert(0, "/root/workspace/FinceptTerminal")
from trade_mcp.common import ensure_script_paths

ensure_script_paths()

import pandas as pd
import paper_trading as pt
import yfinance as yf
from bt_strategies import _rolling_mean, _ema

# 统一策略参数 — 与 trade_mcp/research_server.py STRATEGY_PARAMS 保持一致，
# 确保回测/信号/模拟盘回放三者对齐。
SMA_SHORT = 20
SMA_LONG = 50
INITIAL = 100000.0
CURRENCY = "USD"
FEE_RATE = 0.001
MAX_POSITION_PCT = 0.95  # 单笔最大仓位（避免手续费导致余额不足）


def fetch(symbol, start, end):
    t = yf.Ticker(symbol)
    df = t.history(start=start, end=end)
    return df


def compute_signals(df, strategy):
    """返回每行信号: 1买入 / -1卖出 / 0持有"""
    close = df["Close"].values
    n = len(close)
    sig = [0] * n
    if strategy == "sma_crossover":
        fast = _rolling_mean(close, SMA_SHORT)
        slow = _rolling_mean(close, SMA_LONG)
        for i in range(1, n):
            if i < SMA_LONG:
                continue
            if fast[i - 1] <= slow[i - 1] and fast[i] > slow[i]:
                sig[i] = 1
            elif fast[i - 1] >= slow[i - 1] and fast[i] < slow[i]:
                sig[i] = -1
    elif strategy == "ema_crossover":
        fast = _ema(close, SMA_SHORT)
        slow = _ema(close, SMA_LONG)
        for i in range(1, n):
            if i < SMA_LONG:
                continue
            if fast[i - 1] <= slow[i - 1] and fast[i] > slow[i]:
                sig[i] = 1
            elif fast[i - 1] >= slow[i - 1] and fast[i] < slow[i]:
                sig[i] = -1
    else:
        raise ValueError(f"unknown strategy: {strategy}")
    return sig


def main():
    symbol = sys.argv[1] if len(sys.argv) > 1 else "1810.HK"
    strategy = sys.argv[2] if len(sys.argv) > 2 else "sma_crossover"
    start = sys.argv[3] if len(sys.argv) > 3 else "2026-02-01"
    end = sys.argv[4] if len(sys.argv) > 4 else "2026-08-01"

    print(f"=== 模拟盘引擎回测: {symbol} | {strategy} | {start} → {end} ===")
    print(f"初始资金: {INITIAL:,.0f} {CURRENCY} | 手续费率: {FEE_RATE}")

    df = fetch(symbol, start, end)
    if df is None or df.empty:
        print(f"FAIL: 无数据 {symbol}")
        return
    print(f"K线: {len(df)}个交易日 ({df.index[0].date()} → {df.index[-1].date()})")

    sig = compute_signals(df, strategy)
    n_buys = sum(1 for s in sig if s == 1)
    n_sells = sum(1 for s in sig if s == -1)
    print(f"信号: {n_buys}次买入 / {n_sells}次卖出")

    # 创建一次性组合
    pt._init_db_singleton()
    p = pt.create_portfolio(
        name=f"replay-{symbol.replace('.','-')}-{datetime.now().strftime('%H%M%S')}",
        balance=INITIAL, currency=CURRENCY, leverage=1.0,
        margin_mode="cross", fee_rate=FEE_RATE,
    )
    pid = p["id"]

    trades_log = []
    holding = 0.0
    last_price = None

    for i in range(len(df)):
        price = float(df["Close"].iloc[i])
        last_price = price
        date = df.index[i].strftime("%Y-%m-%d")
        s = sig[i]

        if s == 1 and holding == 0:
            # 金叉：用当前余额全仓买入（留手续费空间）
            bal = None
            for pr in pt.list_portfolios():
                if pr["id"] == pid:
                    bal = pr["balance"]
                    break
            if bal is None:
                bal = INITIAL
            budget = bal * MAX_POSITION_PCT
            qty = int(budget / price)
            if qty <= 0:
                continue
            o = pt.place_order(pid, symbol, "buy", "market", float(qty), price)
            if isinstance(o, dict) and o.get("error"):
                print(f"  [{date}] 买入失败: {o['error']}")
                continue
            pt.fill_order(o["id"], price)
            holding = qty
            trades_log.append((date, "BUY", qty, price))
            print(f"  [{date}] BUY  {qty}股 @ {price:.2f}")

        elif s == -1 and holding > 0:
            # 死叉：全部卖出
            o = pt.place_order(pid, symbol, "sell", "market", float(holding), price)
            if isinstance(o, dict) and o.get("error"):
                print(f"  [{date}] 卖出失败: {o['error']}")
                continue
            pt.fill_order(o["id"], price)
            trades_log.append((date, "SELL", holding, price))
            print(f"  [{date}] SELL {holding}股 @ {price:.2f}")
            holding = 0.0

    # 末日处理：强制平仓或标记
    if holding > 0 and last_price:
        pt.mark_price(pid, symbol, last_price)

    stats = pt.get_stats(pid)
    positions = pt.get_positions(pid)
    balance = None
    for pr in pt.list_portfolios():
        if pr["id"] == pid:
            balance = pr["balance"]
            break

    # 总资产 = 现金 + 持仓市值（balance 是现金语义）
    holding_value = 0.0
    for pos in positions:
        qty = pos.get("quantity", 0)
        px = pos.get("current_price") or pos.get("entry_price") or last_price
        holding_value += float(qty) * float(px)
    total_assets = (balance or 0) + holding_value

    print(f"\n=== 订单级结果 ===")
    print(f"  成交笔数: {len(trades_log)}（{n_buys}买 {n_sells}卖）")
    print(f"  期末现金: {balance:,.2f} {CURRENCY}")
    print(f"  期末持仓市值: {holding_value:,.2f}（{len(positions)}只）")
    print(f"  总资产:   {total_assets:,.2f} {CURRENCY}")
    print(f"  总收益:   {(total_assets/INITIAL - 1)*100:+.2f}%")
    print(f"  平仓盈亏: {stats.get('total_pnl',0):,.2f}")
    print(f"  胜率:     {stats.get('win_rate',0)*100:.1f}%")
    print(f"  盈利笔:   {stats.get('winning_trades',0)} | 亏损笔: {stats.get('losing_trades',0)}")
    print(f"  最大单笔赢: {stats.get('largest_win',0):,.2f} | 最大单笔亏: {stats.get('largest_loss',0):,.2f}")
    print(f"  总手续费: {stats.get('total_fees',0):,.2f}")

    # 对比买入持有
    first = float(df["Close"].iloc[0])
    bh_ret = (last_price / first - 1) * 100
    print(f"  买入持有对比: {bh_ret:+.2f}%")

    # 清理
    pt.delete_portfolio(pid)


if __name__ == "__main__":
    main()
