# AGENTS.md — Fincept 交易 Agent 指令

- 行情/模拟盘/回测/基本面数据一律走 MCP 工具（`market_*` `paper_*` `research_*` `fundamentals_*` `macro_*` `china_*`）
- 禁止写脚本直调库（yfinance/paper_trading/bt）取数或下单
- 工具失败 → 说明原因 + 换备选，绝不编造数据

（其余规则后续确认再补）
