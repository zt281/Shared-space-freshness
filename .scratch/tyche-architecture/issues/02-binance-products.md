# Binance 产品与官方接入能力

Type: research
Labels: wayfinder:research
Status: resolved
Assignee: research-binance
Parent: ../map.md
Blocked by: none

## Question

截至调研时，Binance 的哪些官方产品和接口符合用户所说的「加密货币和加密货币计价的股票及衍生品」？区分现货、期货、期权、股票相关衍生品或代币化权益，以及计价、保证金、结算资产。说明有证据支持的接口、模拟环境、账户或地区限制，并列出必须向用户确认的产品歧义；不要把未查到的产品断言为不存在。

## Answer

2026-09-10：完成公开官方资料调查，结论与逐项来源见 [Binance 产品与官方接入能力](../research/binance-products.md)。研究保存在 `research/binance-products`，提交 `1a2fcad61b0738a4485ac194f12f7ef9b18691d6`。

股票相关需求需区分 Direct Stocks、bStocks、Alpha/Ondo 与 TradFi 永续；它们的权益、资金与接口语义不同。报告同时记录 UM/CM 共享控制的公告、期权做市权限差异，以及模拟环境和产品 API 尚未核实的部分。

研究完成不代表用户选择了全部产品或已具有相关权限。下一步由 [Binance 首版产品与交易权限范围](12-binance-scope.md) 收敛产品；选择之后再调查其未确认的具体接入能力。
