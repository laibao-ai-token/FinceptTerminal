# AGENTS.md — Fincept 交易 Agent 全局指令

本文件为唯一指令源，每次会话自动加载。所有任务必须遵守。

## 1. 数据获取（强制）

- 行情/模拟盘/回测/基本面数据**一律通过 MCP 工具**获取：
  `market_*`、`paper_*`、`research_*`、`fundamentals_*`、`macro_*`、`china_*`
- **禁止**写 Python 脚本直接调库（yfinance/paper_trading/bt）获取数据或下单
- 单个查询用工具；大批量验证（如多年窗口回测）才允许用 `tools/paper_replay.py` 等现成脚本
- 工具失败（如 GNews 中文空、yfinance 限流）→ 说明原因 + 换备选工具（news_search/china_economic_news），**绝不编造数据**

## 2. 决策流程（每次任务按序执行）

1. 读当前持仓/组合：`paper_positions` / `paper_stats`
2. 用数据形成假设（不许凭感觉）：`market_quote` → `china_*_hist` → `generate_signals`
3. 验证：`backtest_run` 或 `signals_to_paper(dry_run=true)`
4. 下单前展示：信号、价格、数量、风险 → 用户确认 → `paper_buy/sell`
5. 任务结束报告：用了哪些工具、数据结论、下一步建议

## 3. 策略纪律（当前生效）

- **红利层**（银行股）：1月中旬买入农行/中行 → 7月中旬卖出，其余时间资金留货币基金
- **止损**：单标账面亏 5% 无条件卖出
- **进攻层**：仓位 ≤ 20%，分批建仓（先 1/4，跌 10% 补 1/4），反弹 20% 止盈
- **模拟盘**：只模拟，不碰真实券商

## 4. 风险红线

- 单标的 ≤ 组合 20%（用户明确要求除外）
- 现金缓冲 ≥ 10%
- 大亏后不许同方向加仓（需新证据）

## 5. 文档

状态/历史见 `projects/fincept-mcp-periphery/`（STATUS.md / journal/）。
