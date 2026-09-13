# 手工与自动交易的订单、风控和恢复语义

Type: grilling
Labels: wayfinder:grilling
Status: open
Assignee: none
Parent: ../map.md
Blocked by: 01, 04, 05, 06

## Question

手工指令和自动策略共享账户时，订单、持仓归属和风控应如何协调？对提交结果未知、部分成交、撤单竞争、重复回报、重连及重启逐项定义可观察行为。明确订单状态的权威来源、恢复前的交易限制，以及停止策略、撤销挂单和紧急操作的不同含义。

沿用 [工作台决议](05-workbench-workflow.md) 的价格梯点击、监控面板操作、固定账户/策略对象、显式重新启用与状态失效展示要求；前端交互限制不能替代后台的指令校验、风控及恢复前置条件。

结合 [Binance 首版范围](12-binance-scope.md) 与 [衍生品能力研究](22-binance-crypto-market-making.md)，明确期权卖出开仓的准入检查，以及 MMP、Options/Futures 倒计时撤单哪些属于策略必需能力。缺少权限时的启动限制、保护范围与回读、停止发单和交易所实际撤单的差异须明确定义；不能把同一账户的各产品可用保证金直接合并抵扣。
