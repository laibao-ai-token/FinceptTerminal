#!/usr/bin/env python3
"""每日自动模拟交易循环 — 10万RMB, A股+港股混合, SMA均线交叉策略

选股池:
  - 600519 茅台 (A股, .SS)
  - 300750 宁德时代 (A股, .SZ)
  - 01810 小米 (港股, .HK)
  - 00700 腾讯 (港股, .HK)

策略:
  - SMA(5日)上穿SMA(20日) → 买入信号
  - SMA(5日)下穿SMA(20日) → 卖出信号
  - 单只仓位不超过总资产的30%
  - 每次操作后更新日报

用法:
  python daily_loop.py              # 跑一轮
  python daily_loop.py --report     # 只看当前持仓和日报
"""
import asyncio, os, json, sys, time
from datetime import datetime, timedelta, timezone

os.environ["PYTHONPATH"] = "/root/workspace/FinceptTerminal"
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

PYBIN = "/root/workspace/FinceptTerminal/.venv-pt/bin/python"
ROOT = "/root/workspace/FinceptTerminal"
ENV = {**os.environ, "PYTHONPATH": ROOT}

PORTFOLIO_NAME = "agile-sma-100k-cny"
INITIAL_BALANCE = 100000.0
CURRENCY = "CNY"

WATCHLIST = [
    {"symbol": "600519", "market": "A", "name": "茅台", "yf_sym": "600519.SS"},
    {"symbol": "300750", "market": "A", "name": "宁德时代", "yf_sym": "300750.SZ"},
    {"symbol": "01810", "market": "HK", "name": "小米", "yf_sym": "1810.HK"},
    {"symbol": "00700", "market": "HK", "name": "腾讯", "yf_sym": "0700.HK"},
]

MAX_POSITION_PCT = 0.30  # 单只最多30%仓位
SMA_SHORT = 5
SMA_LONG = 20


def parse(r):
    t = r.content[0].text if r.content else str(r)
    try:
        return json.loads(t)
    except Exception:
        return t


async def mcp_call(session, tool, args=None):
    r = await session.call_tool(tool, args or {})
    return parse(r)


async def get_or_create_portfolio(session):
    """找已有组合或创建新的"""
    r = await mcp_call(session, "paper_list", {})
    portfolios = r if isinstance(r, list) else r.get("data", r) if isinstance(r, dict) else []
    for p in portfolios:
        if isinstance(p, dict) and p.get("name") == PORTFOLIO_NAME:
            return p["id"], p
    # Create new
    r = await mcp_call(session, "paper_create", {
        "name": PORTFOLIO_NAME,
        "balance": INITIAL_BALANCE,
        "currency": CURRENCY,
    })
    d = r if isinstance(r, dict) else {}
    pid = d.get("id", d.get("portfolio_id", ""))
    print(f"  [CREATE] 新组合已创建: {pid}")
    return pid, d


async def fetch_price(session, stock):
    """通过market服务器拿实时报价"""
    try:
        r = await mcp_call(session, "market_quote", {"symbol": stock["yf_sym"]})
        if isinstance(r, dict) and r.get("price"):
            return r["price"], r
    except Exception:
        pass
    return None, None


async def fetch_history(session, stock):
    """通过china服务器拿历史K线（用于SMA计算）"""
    server = "china"
    tool = "a_share_hist" if stock["market"] == "A" else "hk_hist"
    try:
        params = StdioServerParameters(
            command=PYBIN, args=["-m", f"trade_mcp.{server}_server"], cwd=ROOT, env=ENV
        )
        async with stdio_client(params) as (rd, wr):
            async with ClientSession(rd, wr) as s:
                await s.initialize()
                r = await mcp_call(s, tool, {
                    "symbol": stock["symbol"],
                    "start_date": (datetime.now(timezone.utc) - timedelta(days=400)).strftime("%Y%m%d"),
                    "end_date": datetime.now(timezone.utc).strftime("%Y%m%d"),
                })
                if isinstance(r, dict):
                    return r.get("data", [])
    except Exception:
        pass
    return []


def compute_sma(closes, period):
    """计算SMA"""
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def compute_signals(hist_data):
    """从历史数据计算SMA交叉信号"""
    closes = []
    for row in hist_data:
        close = row.get("close") or row.get("收盘") or row.get("Close")
        if close is not None:
            closes.append(float(close))

    if len(closes) < SMA_LONG + 2:
        return {"signal": "none", "sma_short": None, "sma_long": None, "closes": closes}

    sma_short_now = compute_sma(closes, SMA_SHORT)
    sma_long_now = compute_sma(closes, SMA_LONG)
    sma_short_prev = compute_sma(closes[:-1], SMA_SHORT)
    sma_long_prev = compute_sma(closes[:-1], SMA_LONG)

    signal = "hold"
    if sma_short_prev and sma_long_prev:
        if sma_short_prev <= sma_long_prev and sma_short_now > sma_long_now:
            signal = "buy"  # 金叉
        elif sma_short_prev >= sma_long_prev and sma_short_now < sma_long_now:
            signal = "sell"  # 死叉

    return {
        "signal": signal,
        "sma_short": round(sma_short_now, 2) if sma_short_now else None,
        "sma_long": round(sma_long_now, 2) if sma_long_now else None,
        "last_close": closes[-1] if closes else None,
        "closes": closes,
    }


async def get_positions(session, pid):
    """获取当前持仓"""
    r = await mcp_call(session, "paper_positions", {"portfolio_id": pid})
    if isinstance(r, list):
        return r
    return r.get("data", r) if isinstance(r, dict) else []


async def get_stats(session, pid):
    """获取组合统计"""
    r = await mcp_call(session, "paper_stats", {"portfolio_id": pid})
    return r if isinstance(r, dict) else {}


async def run_daily_loop():
    report_lines = []
    report_lines.append(f"{'='*60}")
    report_lines.append(f"  每日模拟交易循环 — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    report_lines.append(f"  组合: {PORTFOLIO_NAME} | 初始资金: {INITIAL_BALANCE:,.0f} {CURRENCY}")
    report_lines.append(f"  策略: SMA({SMA_SHORT})/SMA({SMA_LONG}) 均线交叉")
    report_lines.append(f"  选股池: {[s['name'] for s in WATCHLIST]}")
    report_lines.append(f"{'='*60}")

    # ---- Phase 1: 创建/获取组合 ----
    paper_params = StdioServerParameters(
        command=PYBIN, args=["-m", "trade_mcp.paper_server"], cwd=ROOT, env=ENV
    )
    market_params = StdioServerParameters(
        command=PYBIN, args=["-m", "trade_mcp.market_server"], cwd=ROOT, env=ENV
    )

    async with stdio_client(paper_params) as (paper_rd, paper_wr):
        async with ClientSession(paper_rd, paper_wr) as paper_session:
            await paper_session.initialize()

            pid, pinfo = await get_or_create_portfolio(paper_session)
            report_lines.append(f"\n组合ID: {pid}")

            # 获取初始状态
            positions = await get_positions(paper_session, pid)
            stats = await get_stats(paper_session, pid)
            balance = stats.get("balance", INITIAL_BALANCE)
            report_lines.append(f"当前余额: {balance:,.2f} {CURRENCY}")
            report_lines.append(f"当前持仓: {len(positions)} 只")
            for pos in positions:
                report_lines.append(f"  - {pos.get('symbol','?')}: {pos.get('quantity','?')} 股 @ {pos.get('avg_price','?')}")

            # ---- Phase 2: 逐只分析+交易 ----
            report_lines.append(f"\n{'─'*60}")
            report_lines.append(f"  Phase 2: 信号分析 & 交易执行")
            report_lines.append(f"{'─'*60}")

            for stock in WATCHLIST:
                name = stock["name"]
                sym = stock["symbol"]
                report_lines.append(f"\n  [{name} ({sym})]")

                # 2a: 获取实时价格
                async with stdio_client(market_params) as (mkt_rd, mkt_wr):
                    async with ClientSession(mkt_rd, mkt_wr) as mkt_session:
                        await mkt_session.initialize()
                        price, quote = await fetch_price(mkt_session, stock)

                if price:
                    report_lines.append(f"    现价: {price} {'HKD' if stock['market']=='HK' else 'CNY'}")
                    if quote:
                        chg = quote.get("change_percent", 0)
                        report_lines.append(f"    今日涨跌: {chg:+.2f}%")
                else:
                    report_lines.append(f"    现价: 获取失败")

                # 2b: 获取历史K线 & 计算SMA信号
                hist = await fetch_history(None, stock)
                if not hist:
                    report_lines.append(f"    历史K线: 获取失败，跳过")
                    continue

                sig = compute_signals(hist)
                report_lines.append(f"    SMA{SMA_SHORT}: {sig['sma_short']} | SMA{SMA_LONG}: {sig['sma_long']}")
                report_lines.append(f"    信号: {sig['signal'].upper()}")

                # 2c: 执行交易
                if sig["signal"] == "buy":
                    if not price:
                        report_lines.append(f"    现价获取失败，跳过买入")
                        continue
                    max_invest = balance * MAX_POSITION_PCT
                    qty = int(max_invest / price / 100) * 100  # 港股100股一手
                    if qty < 100:
                        qty = 100
                    cost = qty * price
                    if stock["market"] == "HK":
                        cost_cny = cost * 0.91  # HKD→CNY approx
                    else:
                        cost_cny = cost
                    if cost_cny > balance:
                        qty = int(balance / price / 100) * 100
                        cost_cny = qty * price * (0.91 if stock["market"] == "HK" else 1)
                    if qty <= 0:
                        report_lines.append(f"    余额不足，无法买入")
                        continue

                    report_lines.append(f"    → 买入 {qty} 股 @ {price} (约 {cost_cny:,.0f} CNY)")
                    r = await mcp_call(paper_session, "paper_buy", {
                        "portfolio_id": pid,
                        "symbol": stock["yf_sym"],
                        "quantity": qty,
                        "price": price,
                    })
                    if isinstance(r, dict) and r.get("error"):
                        report_lines.append(f"    买入失败: {r['error']}")
                    else:
                        report_lines.append(f"    买入成功 ✓")
                        balance -= cost_cny

                elif sig["signal"] == "sell":
                    pos = None
                    for p in positions:
                        if stock["yf_sym"] in str(p.get("symbol", "")):
                            pos = p
                            break
                    if pos:
                        qty = pos.get("quantity", 0)
                        if not price:
                            report_lines.append(f"    现价获取失败，跳过卖出")
                            continue
                        report_lines.append(f"    → 卖出 {qty} 股 @ {price}")
                        r = await mcp_call(paper_session, "paper_sell", {
                            "portfolio_id": pid,
                            "symbol": stock["yf_sym"],
                            "quantity": qty,
                            "price": price,
                        })
                        if isinstance(r, dict) and r.get("error"):
                            report_lines.append(f"    卖出失败: {r['error']}")
                        else:
                            report_lines.append(f"    卖出成功 ✓")
                            proceeds = qty * price * (0.91 if stock["market"] == "HK" else 1)
                            balance += proceeds
                    else:
                        report_lines.append(f"    无持仓，跳过卖出")

            # ---- Phase 3: 组合日报 ----
            report_lines.append(f"\n{'─'*60}")
            report_lines.append(f"  Phase 3: 组合日报")
            report_lines.append(f"{'─'*60}")

            final_positions = await get_positions(paper_session, pid)
            final_stats = await get_stats(paper_session, pid)
            final_balance = final_stats.get("balance", balance)
            total_pnl = final_stats.get("total_pnl", 0)
            win_rate = final_stats.get("win_rate", 0)
            total_trades = final_stats.get("total_trades", 0)

            report_lines.append(f"\n  余额: {final_balance:,.2f} {CURRENCY}")
            report_lines.append(f"  持仓数: {len(final_positions)}")
            report_lines.append(f"  累计盈亏: {total_pnl:,.2f} {CURRENCY}")
            report_lines.append(f"  总交易次数: {total_trades}")
            report_lines.append(f"  胜率: {win_rate:.1%}")
            report_lines.append(f"  收益率: {(final_balance/INITIAL_BALANCE - 1)*100:+.2f}%")

            for pos in final_positions:
                sym = pos.get("symbol", "?")
                qty = pos.get("quantity", 0)
                avg = pos.get("entry_price") or pos.get("avg_price") or 0
                report_lines.append(f"    {sym}: {qty} 股 @ {avg} (成本 {qty*avg:,.0f})")

            report_lines.append(f"\n{'='*60}")
            report_lines.append(f"  循环结束 — {datetime.now(timezone.utc).strftime('%H:%M UTC')}")
            report_lines.append(f"{'='*60}")

    return "\n".join(report_lines)


async def run_report_only():
    """只查看当前组合状态"""
    paper_params = StdioServerParameters(
        command=PYBIN, args=["-m", "trade_mcp.paper_server"], cwd=ROOT, env=ENV
    )
    async with stdio_client(paper_params) as (rd, wr):
        async with ClientSession(rd, wr) as s:
            await s.initialize()
            pid, _ = await get_or_create_portfolio(s)
            positions = await get_positions(s, pid)
            stats = await get_stats(s, pid)
            balance = stats.get("balance", 0)
            pnl = stats.get("total_pnl", 0)
            trades = stats.get("total_trades", 0)
            wr = stats.get("win_rate", 0)

            print(f"{'='*50}")
            print(f"  组合: {PORTFOLIO_NAME}")
            print(f"  余额: {balance:,.2f} {CURRENCY}")
            print(f"  收益率: {(balance/INITIAL_BALANCE-1)*100:+.2f}%")
            print(f"  累计盈亏: {pnl:,.2f}")
            print(f"  总交易: {trades} 次 | 胜率: {wr:.1%}")
            print(f"  持仓 ({len(positions)}):")
            for p in positions:
                print(f"    {p.get('symbol','?')}: {p.get('quantity','?')} 股 @ {p.get('entry_price') or p.get('avg_price','?')}")
            print(f"{'='*50}")


if __name__ == "__main__":
    if "--report" in sys.argv:
        asyncio.run(run_report_only())
    else:
        report = asyncio.run(run_daily_loop())
        print(report)
        # Save report
        ts = datetime.now(timezone.utc).strftime("%Y%m%d")
        report_path = f"/root/workspace/FinceptTerminal/projects/fincept-mcp-periphery/journal/daily-report-{ts}.txt"
        with open(report_path, "w") as f:
            f.write(report)
        print(f"\n日报已保存: {report_path}")
