# Binance 美韩股票相关产品的 USDT 开空与 API 能力

Type: research
Labels: wayfinder:research
Status: resolved
Assignee: codex-equity-research
Parent: ../map.md
Blocked by: none

## Question

为 [股票接入通道选择](23-stock-short-selling-access.md) 核实 Binance 美股及韩国公司相关产品，重点 SK 海力士、三星。用户接受自动借券及衍生品，要求无已有多头时建立空头，股票侧限 Binance 与 USDT，暂不接受独立美元账户。

仅用官方资料区分 Direct Stocks、bStocks、股票相关永续，核实具体产品/代码、USDT 资金及结算、卖出开仓、地区和账户权限、API 行情/报撤单/账户回报路径、网关依赖、交易时段与休市行为、资金费、限流和模拟验证条件。产品不存在或事实未核实应明确，不能将某个韩国公司产品等同于覆盖韩国交易所。重点回答哪个路径可作为首版候选及还需哪些产品取舍。

研究资产存于 ../research/binance-equity-short-access.md；研究分支 research/binance-equity-short-access。不得访问凭据或执行交易。研究结果不替代用户产品选择。

## Resolution comment — 2026-09-14

官方公告与公共生产 API 确认 USDT 股票 TradFi 永续候选，包括 SKHYNIXUSDT、SAMSUNGUSDT 及多个美国股票产品。USDⓈ-M API 提供报撤单和账户流，产品另有 TradFi 协议；个人账户地区、开通和交易权限未核实。公开生产及 Demo 目录已只读实测，Demo 有三星与 SKHYNIX，但两者分类与生产不一致，不能替代生产验证。资金费当前两韩股样本为每 4 小时、上限 ±0.50%；底层休市切换指数模式，合约仍 24/7。未执行账户操作、协议签署或交易。

研究资产：[Binance 美韩股票相关产品的 USDT 开空与 API 能力](../research/binance-equity-short-access.md)。原始研究分支 `research/binance-equity-short-access`，独立工作区 `/tmp/tyche-equity-research`；产品范围由父决策票记录，研究结论不替代产品决策。
