# Binance 产品与官方接入能力

调研日期：2026-09-10。用途：为 Tyche 架构决策提供事实输入，不替用户选择首版产品。来源限定为 Binance 官方公告、学院、支持中心、开发者文档及官方 GitHub；未登录、未发交易请求、未验证个人账户权限。文档存在、产品已公告、某账户实际可交易，是三个不同层次的证据。

## 结论

“用加密货币交易股票”至少包含四种不同产品：Direct Stocks、bStocks、Alpha/Ondo 代币化证券和 TradFi 股票挂钩永续。不能把这些都建模为同一种股票，也不能用历史股票代币下架事件推断当前产品不存在。2026 年官方分别说明了 [Direct Stocks 与 bStocks](https://www.binance.com/en/blog/markets/3291762588579390744)、[Alpha/Ondo](https://www.binance.com/en-IN/support/announcement/detail/45bc5a87a2534f47879de7dcbe5b4934) 和 [股票永续](https://www.binance.com/en/academy/articles/how-to-trade-stock-perpetual-contracts-on-binance)。

| 产品 | 标的与资产语义 | 报价、保证金、结算及权益 | 官方证据与时效 |
| --- | --- | --- | --- |
| Crypto Spot | 交易对中的基础资产与计价资产 | 现货兑换；不能把资金资产、报价资产、保证金资产合并成一个字段 | [Spot REST](https://developers.binance.com/en/docs/products/spot/rest-api)；实时交易对规则以 exchangeInfo 为准 |
| USDⓈ-M / COIN-M Futures | 加密资产期货；是否永续、到期与合约面值须逐合约读取 | USDⓈ-M 为稳定币结算，COIN-M 为币结算；保证金模式与结算资产需独立表达 | [Options/Futures 对比](https://www.binance.com/en/support/faq/detail/374321c9317c473480243365298b8706)，更新 2026-01-12；具体规格另核 |
| TradFi Perpetuals | 股票、ETF、商品等传统标的的价格敞口 | 已查股票示例为 USDT 结算；不是股票所有权。Multi-Assets Mode 可让其他资产充当抵押，不改变示例合约的 USDT 结算语义 | [股票永续指南](https://www.binance.com/en/academy/articles/how-to-trade-stock-perpetual-contracts-on-binance)，页面标注更新 2026-04-23；不能将示例币种、杠杆、时段参数推广至全部未来合约 |
| Direct Stocks | 经券商体系买卖上市股票/ETF | 官方说明用户为股份受益所有人，券商伙伴托管；买入使用 USDC，支持的其他支付资产先转换，卖出款回到 Funding Account；这不同于股票本身以 BTC 计价 | [Stocks Trading 指南](https://www.binance.com/en/academy/articles/what-is-binance-stocks-trading)，更新 2026-06-04；地区与功能受资格限制 |
| bStocks | 对指定证券的代币化经济敞口 | 不直接成为标的公司股东；可以在 Binance Spot 交易。公司行动、转换及赎回依产品条款处理，不能直接套用普通股票股数和现金分红模型 | [bStocks FAQ](https://www.binance.com/en-AU/support/faq/detail/f0c03cd6509a4085b4cce1636f16be38)；访问 2026-09-10，优先于营销文章的简化描述 |
| Alpha / Ondo tokenized securities | 第三方 Ondo 发行的股票/ETF 链上价格敞口 | 可用 CEX 资金购买，支持市价和限价；公告明确不代表相关标的所有权，赎回由发行方设条件。具体 token、交易对、链、报价与赎回资产本轮未逐一核实 | [Alpha 公告](https://www.binance.com/en-IN/support/announcement/detail/45bc5a87a2534f47879de7dcbe5b4934)，2026-02-24 发布、03-09 更新 |
| Crypto Options / Commodity Options | 加密资产期权，以及已公告的黄金、白银商品期权 | 加密期权官方说明稳定币报价/结算；商品期权明确欧式、USDT 报价和结算、无实物交割。期权买入权利金与卖方保证金应区分 | [加密期权介绍](https://www.binance.com/en/support/faq/detail/374321c9317c473480243365298b8706)、[商品期权 FAQ](https://www.binance.com/de/support/faq/detail/dc9e52b4440b48bd900a767cc5024c84)，后者发布 2026-07-29 |

## 官方接口与模拟环境

以下仅列架构入口，不构成完整接口清单；API 文档中的路径应与部署时版本再次核对。

| 接入面 | 行情与订单入口 | 已核实的模拟环境 |
| --- | --- | --- |
| Spot | REST `/api/v3/*`，行情与交易 WebSocket；REST 基址 `https://api.binance.com` | `https://testnet.binance.vision/api`，配套 WebSocket 地址。官方明确 Spot Testnet 仅支持 `/api`，不支持 `/sapi`，且会定期重置。[官方 Testnet 说明](https://raw.githubusercontent.com/binance/binance-spot-api-docs/master/testnet/general-info.md) |
| USDⓈ-M | `https://fapi.binance.com`；`POST /fapi/v1/order`；REST、WebSocket API、行情流分别成面 | `https://demo-fapi.binance.com`、`wss://demo-fstream.binance.com`；文档只承诺“大多数接口”。[General Info](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/general-info)、[接口目录](https://developers.binance.com/en/docs/catalog) |
| COIN-M | `https://dapi.binance.com`；`POST /dapi/v1/order`；有 REST、WebSocket API 和行情流 | `https://demo-dapi.binance.com`、`wss://demo-dstream.binance.com`。[General Info](https://developers.binance.com/en/docs/products/derivatives-trading-coin-futures/general-info)、[整合通知](https://developers.binance.com/en/docs/products/derivatives-trading-coin-futures/Important-CM-UM-Integration-Notice) |
| TradFi Perps | 归入 USDⓈ-M；`POST /fapi/v1/stock/contract` 是签署产品协议，不是下单端点；普通订单使用相应 Futures 交易接口 | 不能由 Futures 有 demo 推断每个股票永续标的、协议和权限都在 demo 可用。[Futures Trade](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/trade) |
| Options | `https://eapi.binance.com`；行情 `/eapi/v1/exchangeInfo`、`/depth`，订单 `/eapi/v1/order`；另有行情及账户 WebSocket 流 | 当前 General Info 列 testnet REST 为 `https://demo-fapi.binance.com`，并列 `demo-fstream` 的 `/public/`、`/market/`、`/private/`。保留原文地址，不能擅自改成猜测的 `demo-eapi`；联调时验证具体路径和合约。[General Info](https://developers.binance.com/en/docs/products/derivatives-trading-options/general-info)、[Options API 指南](https://www.binance.com/en/support/faq/detail/fe0be251ac014a8082e702f83d089e54) |
| Direct Stocks / tokenization | 独立 `/sapi/v1/equity/*`；市场信息 `/market/exchangeInfo`，下单 `/order/place`，撤单 `/order/cancel`。`quoteAsset` 默认 USDC；`tokenize` 对支持代币化的标的生效，其他标的按传统股票交易结算 | 本轮未核实 Stocks 专用 demo。Spot Testnet 不支持 `/sapi`，不能直接拿来验证这一接入。[Stocks Trade](https://developers.binance.com/en/docs/catalog/advanced-trading-stocks-trading/api/rest-api/trade) |
| Alpha | 当前官方目录列出独立 Alpha Trading REST / Streams。具体交易端点、Ondo 产品覆盖及账户权限未完整核实 | 未核实；不能因为前端可下单或目录存在就承诺自动策略可接入。[官方目录](https://developers.binance.com/en/docs/catalog) |

bStocks 可在 Spot 交易，是产品层事实；具体 token 是否出现在普通账户的 Spot API、其权限过滤和公司行动推送如何接入，仍需选定标的后验证。[bStocks 指南](https://www.binance.com/en/academy/articles/what-are-bstocks-a-guide-to-tokenized-stocks-on-binance)（更新 2026-06-29）。

## 直接影响架构的限制

- **UM/CM 不可假设账户设置与配额独立。** 官方整合通知发布于 2026-06-10，写明从 06-24 逐步上线、06-30 全部生效：共享持仓模式、IP 请求权重池与账户订单配额，部分全市场流合并，消息增加区分类型的 `st`。这是已公告生效的接口迁移，不是本文设计提议；具体生产账户仍需查询验证。**架构推断：** 分产品适配器仍应共享账户协调和限流组件，不能按 API key 或主机名重复计算预算。[整合通知](https://developers.binance.com/en/docs/products/derivatives-trading-coin-futures/Important-CM-UM-Integration-Notice)
- **期权做市能力不是普通账户默认能力。** 2026-07-29 商品期权 FAQ 明确普通用户可以买入、卖出已有多头平仓，卖出开仓仅向预先批准的期权做市商开放；不能把该条自动外推为所有产品同一权限。2026-05-27 更新的期权 API 指南把 MMP 和断线自动撤单接口列为做市商专用。**架构推断：** 能力表需独立记录卖出开仓、MMP、自动撤单，并把账户资格放在策略启动前检查。[商品期权 FAQ](https://www.binance.com/de/support/faq/detail/dc9e52b4440b48bd900a767cc5024c84)、[Options API 指南](https://www.binance.com/en/support/faq/detail/fe0be251ac014a8082e702f83d089e54)
- **回执、最终订单状态和成交是不同事件。** Futures 的特定 503 表示执行状态未知；官方要求先查订单/账户流防止重复下单。Stocks 的 `S` 只代表请求获接受，不是成交或撤单完成。**架构推断：** OMS 要有未知状态、查询恢复与幂等标识，禁止超时后盲目重发。[Futures General Info](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/general-info)、[Stocks Trade](https://developers.binance.com/en/docs/catalog/advanced-trading-stocks-trading/api/rest-api/trade)
- **毫秒级后台反应不等于毫秒级外部行情。** 期权 API 指南的部分盘口与成交流给出 50ms/100ms 等推送周期，指数/标记价格有 1,000ms 周期。**架构推断：** 性能目标要分别测量行情源间隔、网络延迟、本地处理时间和订单确认；不据此承诺交易所端到端延迟。[Options API 指南](https://www.binance.com/en/support/faq/detail/fe0be251ac014a8082e702f83d089e54)
- **标的身份独立于支付资产。** 同一股票可能对应 Direct Stock、bStock、Ondo token 和永续合约。**架构推断：** `underlying`、`instrument_type`、`venue_product`、`quote_asset`、`collateral_asset`、`settlement_asset`、`payment_asset`、`ownership_form`、交易日历与合约乘数需要可分别表达；具体字段命名等待领域决策。

## 未核实与下一步用户选择

1. 第一批股票相关交易实际需要哪种形态：股票永续、bStocks、Alpha/Ondo，还是经券商托管的 Direct Stocks；可多选，但需排序并给出一两个目标标的。
2. 首版 Binance 是否要现货、USDⓈ-M、COIN-M、加密期权全部支持；期权做市是否主要在 CTP，还是也必须在 Binance 卖出开仓。
3. 用户实际账户的注册实体/适用地区、已开通产品、API 交易权限、期权做市资格、账户模式。本轮只确认公开产品存在，未建立覆盖所有地区的资格矩阵，也不能从中文使用环境推断账户所在地。Futures/Options 需要对应账户开通，[官方 Quick Start](https://developers.binance.com/en/docs/products/derivatives-trading-coin-futures/quick-start)；Stocks 与 Alpha 公告明确可用性依地区而异。
4. 股票交易指南与当前 API 对碎股 GTC 的描述不一致：06-04 学院指南说不支持，API 允许某些延长/24H 时段组合。具体订单能力必须以选定账户的当前接口验证及官方澄清收敛，不能用旧指南硬编码。[Stocks 指南](https://www.binance.com/en/academy/articles/what-is-binance-stocks-trading)、[Stocks Trade](https://developers.binance.com/en/docs/catalog/advanced-trading-stocks-trading/api/rest-api/trade)
5. Alpha/Ondo 的完整程序化下单路径、bStocks 的具体 Spot API 资格、Stocks demo、各新 TradFi 标的 demo 覆盖、股票期权的具体产品/API范围均未在本轮完成核验；这表示仍需按用户选择进一步研究，不表示它们不存在。

研究资产仅记录事实、证据边界和架构推断；产品范围与技术方案尚未据此定案。
