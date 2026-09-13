# Binance 股票产品的程序化交易与做市边界

Type: research
Labels: wayfinder:research
Status: resolved
Assignee: research-binance-stocks
Parent: ../map.md
Blocked by: none

## Question

用户已选择首版同时对 Direct Stocks 与 bStocks 做双边做市。基于当前官方来源核实：两种产品的程序化行情、订单及账户状态入口，具体标的发现方式和可用能力；盘口粒度/推送方式、买卖及卖空/库存约束、订单类型与报价更新/撤单、数量价格精度、交易时段和公司行动等与做市相关的边界。不要把产品上市、API 文档存在与某账户可做市视为同一事实。

核实直接股票与 bStocks 分别是否有明确的 API 资格、产品协议或地区/账户条件，是否有公开可验证的模拟环境；普通 Spot Testnet 不支持 /sapi 的约束仍适用。官方资料未明确的部分应保留为未知，并列出后续怎样验证，不能据此断言产品不可用。

输出一份有直接官方来源、日期/版本边界的中文研究资产。无须遍历全部股票或运行交易测试；不访问用户账户，不获取凭据，不签署协议、不发订单。

## Comments

来源为 [Binance 首版产品与交易权限范围](12-binance-scope.md) 的已确认范围输入：Direct Stocks 与 bStocks，均需双边做市；具体股票样本、库存/借券要求仍在访谈中。

## Answer

2026-09-10，完成官方资料调查，详见 [Binance 股票产品的程序化交易与做市边界](../research/binance-stocks-market-making.md)。

- bStocks 官方 FAQ 明确当前不支持借入 bStocks；可以作为部分保证金产品的抵押资产不等于可以借入该代币做空。Direct Stocks 未找到面向该普通账户的借券、券源或负库存接口，不能据下单存在 SELL、合作券商的其他产品能力或 FPSL 出借计划宣称本需求可用。
- Direct Stocks 已确认 REST 交易与官方 WebSocket BBO/订单流。约 5 秒陈旧是 REST 报价缓存的边界，不能概括为没有实时股票流；多档深度与推送周期未获确认。
- Direct Stocks 当前公开下单额度、订单类型、代币化默认值和盘外撤单行为需单独处理；完整权威库存/可卖量/结算快照及专用模拟环境尚待核验。bStocks Spot 交易对能力则需要独立查询和验证。
- 公开事实已经足以识别用户借券卖空要求与当前已证实能力的冲突；产品范围调整由 [首版范围决议](12-binance-scope.md) 记录。未访问账户或执行交易测试。

研究上下文：独立分支 `research/binance-stocks-market-making`，提交 `71f9f697e375abfb16f48c44df227abc9e71ece6`；完整资产已复制回当前工作目录并通过 SHA256 一致性检查。
