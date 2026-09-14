# 跨市场账户、合约与持仓字段的官方语义

Type: research
Labels: wayfinder:research
Status: resolved
Assignee: codex-domain-facts
Parent: ../map.md
Blocked by: none

## Question

为 [跨市场合约、账户与资金模型](06-market-domain-model.md) 核实 CTP 商品/股指期货期权、Binance 普通账户 BTC/ETH Options 与 USDT 永续（含股票永续）的关键领域差异。先消费已有 research 中的事实和来源，仅对关键缺口核查第一方资料。

聚焦合约标识与行情源/环境区分、CTP 券商/投资者身份和资金查询范围、Binance 登录账户/产品钱包/保证金范围、净持仓/双向持仓/今昨仓及外部订单归属、价格数量精度/乘数和结算币种、交易日/自然日。说明哪些状态是交易通道提供、哪些只能 Tyche 自行归属。不要调查全接口或替用户选择默认币种/归属规则，不把总资产折算当作保证金互通。

输出一份紧凑带官方引用的语义表，标清未核实项及接入验收条件。研究资产 ../research/cross-market-domain-facts.md，研究分支 research/cross-market-domain-facts。仅研究，不访问凭据或交易。

## Resolution comment — 2026-09-14

完成有界第一方核查，产出账户/保证金范围、合约与行情来源、净/双向/今昨持仓、数量规则与交易日语义表。CTP 的 YdPosition 为昨日收盘静态值；Options 有符号数量不等于 Futures 双向模式。策略归属仍为 Tyche 内部账，不由通道账户持仓自动提供。

[研究资产](../research/cross-market-domain-facts.md)，研究分支 `research/cross-market-domain-facts`，提交 `9e15463`，独立工作区 `/tmp/tyche-domain-facts`。当前 CTP SDK 的资金币种/乘数及夜盘细节、实际 Binance 保证金范围和权限尚待接入验收，资产已明确列出；不推测用户账户数量或展示币种，不替用户选择归属规则。研究关闭不表示领域设计已决议。
