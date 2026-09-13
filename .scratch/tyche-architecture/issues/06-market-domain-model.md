# 跨市场合约、账户与资金模型

Type: grilling
Labels: wayfinder:grilling
Status: open
Assignee: none
Parent: ../map.md
Blocked by: 02, 03, 12, 23

## Question

Binance、CTP、QMT 与另选股票通道的产品、交易场所、合约、账户、资金和持仓应如何命名及识别？哪些业务语义可以统一，哪些必须显式保留市场差异？以合约乘数、精度、计价与结算资产、期权属性、交易日和持仓类型等具体例子检验模型，避免用展示代码充当全局身份。

沿用 [Binance 首版范围](12-binance-scope.md)：一个登录账户可以包含多个产品资金和保证金范围；普通/组合保证金、Futures 持仓模式及 Options 卖出开仓模式分别表达。股票需要区分可交易、可借、当前券源和实际库存/负债；目录覆盖与活动合约集合也不能混为一体。具体股票通道的约束由 [接入选择](23-stock-short-selling-access.md) 提供。
