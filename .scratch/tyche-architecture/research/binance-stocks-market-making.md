# Binance 股票产品的程序化交易与做市边界

研究日期：2026-09-10。范围：Direct Stocks 与 bStocks；一个普通账户，实际产品权限与账户模式尚未核验。用户要求两者首版均做双边做市，并把借券卖空列为硬性需求。本文只核查公开官方资料，未访问账户、取得凭据、签署协议或提交订单；未遍历全部股票。

## 结论

**当前证据不能把“两类股票均支持借入卖空做市”列为已满足能力。** bStocks 官方 FAQ 明确当前不支持借入 bStocks，部分符合条件的代币可以作抵押；两者是不同能力。Direct Stocks 找到 REST 下单、WebSocket 报价与订单回报，但未找到向用户提供股票借入、券源、借券费或负持仓的接口；官方股票与永续比较说明还明确将空头能力归于永续，而非直接股份。不能用 `side=SELL`、合作券商自身能力或 FPSL 出借计划来补足这个缺口。来源：[bStocks 抵押 FAQ](https://www.binance.com/en/support/faq/detail/4f5444780f444bf6b39adbec77ef545a)、[官方股票与永续比较 FAQ](https://www.binance.com/en/academy/articles/what-is-spacex-spcx)、[Stocks 交易 API](https://developers.binance.com/en/docs/catalog/advanced-trading-stocks-trading/api/rest-api/trade)。

**更正行情边界：约 5 秒陈旧只适用于 Direct Stocks 的 REST quote 缓存。** 官方另有 WebSocket BBO 流；本文没有确认该流的固定推送周期、完整市场覆盖或端到端延迟承诺。不能由 REST 缓存推断“没有实时股票行情”，也不能由毫秒时间戳推断“达到毫秒交易响应”。来源：[Stocks REST 行情](https://developers.binance.com/en/docs/catalog/advanced-trading-stocks-trading/api/rest-api/market-data)、[官方 Go connector 市场流](https://github.com/binance/binance-connector-go/blob/master/clients/stocks/src/websocketstreams/api_market_streams.go)。

## 已确认事实：程序接口与语义

| 能力 | Direct Stocks | bStocks |
| --- | --- | --- |
| 交易对象 | 券商托管的直接股份；用户取得股份受益所有权。实际执行、清算及结算经 Alpaca，不是 Binance Spot 上的同名股票代币订单簿。[股票产品说明](https://www.binance.com/en/support/faq/detail/a7469c7703524024b5bc2d492b03639d)、[股票 FAQ](https://www.binance.com/en/support/faq/detail/7ae9ef8636e74e8b9c3b625677b83310) | 股价敞口代币化证券，不是直接股份，不赋予股东权利；可在 Binance Spot 24/7 交易，但仍有产品、地区与标的资格限制。[bStocks FAQ](https://www.binance.com/en/support/faq/detail/f0c03cd6509a4085b4cce1636f16be38) |
| 标的发现 | `GET /sapi/v1/equity/market/exchangeInfo`：可按 symbol 查询；包括买卖资格、时段、碎股、数量步长、金额和价格限制。接口要求 API key，非签名行情接口。[Stocks REST 行情](https://developers.binance.com/en/docs/catalog/advanced-trading-stocks-trading/api/rest-api/market-data) | `/equity/market/tokenized-assets` 提供 underlying 股票、assetCode 与 multiplier 映射；这只证明代币化映射，不能证明 Spot 交易对已开放。须再对已选交易对查询 Spot `exchangeInfo`，核验 status、base/quote、permissions、filters 与订单能力。[Stocks REST 行情](https://developers.binance.com/en/docs/catalog/advanced-trading-stocks-trading/api/rest-api/market-data)、[Spot REST](https://github.com/binance/binance-spot-api-docs/blob/master/rest-api.md#exchange-information) |
| 下单入口 | `POST /sapi/v1/equity/order/place`；当前列 MARKET/LIMIT × BUY/SELL。DAY 默认，GTC 仅 LIMIT；限价需 price、quantity、tradingSession。市场买按 notional、市场卖按 quantity。下单列 200 requests/min，按 UID。[Stocks 交易 API](https://developers.binance.com/en/docs/catalog/advanced-trading-stocks-trading/api/rest-api/trade) | 已上市且账户可交易的 bStocks Spot 对，应走 Spot 订单家族；不能将 `/equity/order/place` 的股票买入并代币化等同于 bStocks Spot 挂单。Spot 通用订单入口为 `POST /api/v3/order`，具体能力必须服从该对元数据。[Spot REST](https://github.com/binance/binance-spot-api-docs/blob/master/rest-api.md#new-order-trade) |
| 撤改与被动挂单 | 已列单笔 cancel、cancel-all，以及未结订单、订单历史/详情和成交查询。当前页面未列 amend、cancel-replace 或 post-only，不应承诺可保留队列位置改价。下单返回 S/F 是请求确认，不是成交或订单终态。[Stocks 交易 API](https://developers.binance.com/en/docs/catalog/advanced-trading-stocks-trading/api/rest-api/trade) | Spot 通用 LIMIT_MAKER 是 post-only；cancelReplace 需处理撤单/新单分别成功失败；keepPriority amend 只减数量，不能据此实现保优先级改价。对 bStocks 是否允许，读 orderTypes、cancelReplaceAllowed、amendAllowed 等。[Spot REST](https://github.com/binance/binance-spot-api-docs/blob/master/rest-api.md#trading-endpoints) |

### 行情、订单回报与账户状态

Direct Stocks 官方 connector 的 `MarketStreamsAPIService.QuoteStream()` 使用 `/<symbol>@quote`，另列 PriceStream、TradabilityStream 与 KlineStream。Quote 模型只列最优 bid/ask 价格及股数；`E` 是服务器推送时刻，`T` 是可能为空的源报价时刻，单位毫秒。基础地址为 `wss://nbstream.binance.com/equity`。**本轮只确认 BBO；没有确认多档深度、逐笔委托或固定频率。** 开发文档市场流页读取不稳定，以官方 connector 源码补证接口形状，未把 SDK 描述当成交付 SLA。[官方市场流实现](https://github.com/binance/binance-connector-go/blob/master/clients/stocks/src/websocketstreams/api_market_streams.go)、[QuoteStreamResponse 模型](https://github.com/binance/binance-connector-go/blob/master/clients/stocks/src/websocketstreams/models/model_quote_stream_response.go)。

Direct Stocks 用 `POST /sapi/v1/equity/listenKey` 创建/续期 listenKey，订阅 `{listenKey}@orderReport`。订单事件包含 ORDER_UPDATE / ORDER_TERMINAL、累计成交等信息；股票代码可能是 `EQ_AAPL`，而下单和报价使用 `AAPL`。事件出现的订单类型枚举范围大于下单 API，不能反推全部可提交。**当前 Account API 页只列签署声明；完整持仓、可卖数量、冻结数量、结算状态快照及余额/持仓流尚未证实。** 订单回报不能替代这些数据，启动和重连前必须找到权威库存核对方式。[listenKey](https://developers.binance.com/en/docs/catalog/advanced-trading-stocks-trading/api/rest-api/user-data-streams)、[订单流](https://developers.binance.com/en/docs/catalog/advanced-trading-stocks-trading/api/ws-streams/user-streams)、[Account API](https://developers.binance.com/en/docs/catalog/advanced-trading-stocks-trading/api/rest-api/account)。

bStocks 可复用的 **Spot 通用** 行情能力包括实时 bookTicker、逐笔成交、5/10/20 档 partial depth，以及 100ms/1000ms diff depth。重建本地订单簿需要 REST snapshot 和 U/u 序号衔接，缺口须重建；不能把多档聚合量当成逐订单队列。单连接最多 1024 个 streams、24 小时连接寿命；5 条/秒是客户端传入控制消息限制，不是市场事件速率。是否适用于某 bStocks 对仍须通过实际符号与订阅验证。[Spot WebSocket Streams](https://github.com/binance/binance-spot-api-docs/blob/master/web-socket-streams.md)。

Spot 用户流经 WebSocket API 订阅，包含 executionReport、outboundAccountPosition 的 free/locked 余额，以及 balanceUpdate；应与 `/api/v3/account`、订单和成交查询对账。具体 bStocks 数量单位与公司行动调整怎样体现在 API 中，本轮未取得样本证据。[Spot User Data Stream](https://github.com/binance/binance-spot-api-docs/blob/master/user-data-stream.md)、[Spot REST](https://github.com/binance/binance-spot-api-docs/blob/master/rest-api.md#account-information-user_data)。

## 借入卖空：硬性需求与现有证据冲突

| 问题 | 已确认事实 | 不能据此推导的能力 |
| --- | --- | --- |
| 借入 bStocks 后卖出 | FAQ 原文：“Borrowing is not currently supported for bStocks tokens. They can only be used as collateral assets.” 更新于 2026-07-24。[直接 FAQ](https://www.binance.com/en/support/faq/detail/4f5444780f444bf6b39adbec77ef545a) | 当前没有支持“普通账户借入 bStocks 做空”的依据；不能设置 borrowSupported=true。 |
| 拿 bStocks 作抵押 | 部分代币可在 Cross Margin / Portfolio Margin / PM Pro 作抵押，要求符合地区条件及 VIP 3+；支持清单和折算率会变。[同一 FAQ](https://www.binance.com/en/support/faq/detail/4f5444780f444bf6b39adbec77ef545a) | 用 bStocks 抵押所支持的其他币借款，与借入 bStocks 本身分别核验；前者不产生 bStocks 券源，也不证明普通账户符合资格。 |
| Direct Stocks 借券 | 官方 SPCX 产品比较 FAQ 说直接股份不提供永续所具备的杠杆及空头。Stocks 下单 API 未给出借入、偿还、locate 或股票负库存路径。[官方比较](https://www.binance.com/en/academy/articles/what-is-spacex-spcx)、[交易 API](https://developers.binance.com/en/docs/catalog/advanced-trading-stocks-trading/api/rest-api/trade) | 这足以否定“已经确认可做空”的结论，但不是对所有未来产品/专门协议的永久禁止证明。普通账户可用借券流程仍未证实。 |
| FPSL | 用户把自己已持有证券出借，经 Alpaca 转借机构；这是出借人的收益计划。[FPSL FAQ](https://www.binance.com/en/support/faq/detail/ad6885e4afda4e0891707150a8eb6f98) | 出借资格不等于用户可成为借入方；不能把 FPSL 接口或 Alpaca 自身零售 API 的功能直接搬到 Binance。 |

证券产品条款当前为 **v1.4，2026-07-20 生效**；本轮从官方条款页嵌入 PDF 读取，借券相关章节描述用户证券出借及 Alpaca 后续用途，没有取得 Binance 向该普通账户提供借入交易的证据。[条款入口](https://www.binance.com/en/about-legal/terms-securities-trading)、[该版本 PDF](https://bin.bnbstatic.com/static/cms/cg08ou2ak0tn7mcplvfg/file/b1c1af312aed2ec2eeb29944d1f2e1c9e553b15bc78c7618a30837c7c8d868bb.pdf)。

**架构推论：** 有库存的买卖双边报价与允许负库存的借券做市应是两个明确能力。用户已要求后者，故不能默默把它降为“先买库存再卖”。需要保留这一范围冲突，等待产品能力变化、可验证的专门借券安排，或用户改变产品/库存要求；当前研究不代用户作这个决定。

## 时段、精度、结算与公司行动

- Direct Stocks 最多 24/5，仅部分股票支持 overnight；市场单只在 RTH 生效，其他时段可能排队至下次开市；时区应使用 America/New_York 日历及夏令时。未结算卖款用途受限，不能当成立即可提现或可跨所有账户划转的资金。[股票操作说明](https://www.binance.com/en/support/faq/detail/a7469c7703524024b5bc2d492b03639d)
- RTH 限价单在非 RTH 请求取消，可能持续 pending cancellation 至约 07:00 ET 的取消窗口；在最终确认前资金仍冻结，期间仍可能成交。策略风控不能把“发出撤单”当作“风险消失”。[股票 FAQ](https://www.binance.com/en/support/faq/detail/7ae9ef8636e74e8b9c3b625677b83310)
- API 限价最多两位小数；数量和最小金额服从标的参数。当前 API 允许碎股 GTC 与 EXTENDED/24H 组合，而 2026-06-04 Academy 曾写碎股不支持 GTC，存在版本差异；实现应以当前接口、动态参数及验证结果为准。[交易 API](https://developers.binance.com/en/docs/catalog/advanced-trading-stocks-trading/api/rest-api/trade)、[较早 Academy 说明](https://www.binance.com/en/academy/articles/what-is-binance-stocks-trading)
- `tokenize` 在股票买入接口默认 true，仅对启用代币化的股票生效；Direct Stocks 路径应显式 false。`quoteAsset` 默认 USDC，买入钱包可选 CARD/MAIN，而卖款到 CARD；股票市场报价货币、订单支付资产与钱包应分别建模。[交易 API](https://developers.binance.com/en/docs/catalog/advanced-trading-stocks-trading/api/rest-api/trade)
- bStocks 公司行动采用 multiplier；链上 raw token 数量与显示的股票等价数量不能混用，Binance 页面显示量会调整。现金股息处理不同于直接股份；交易、转换或订单也可能因公司行动暂停/取消。不能把 multiplier 恒定为 1，也不能自行假定 Spot API 的数量已经是哪种单位。[bStocks FAQ](https://www.binance.com/en/support/faq/detail/f0c03cd6509a4085b4cce1636f16be38)

**性能推论：** Direct Stocks 下单 200/min/UID 约合平均 3.33 次/秒；这是吞吐约束，不是单笔响应延迟。若策略每次更新一个双边报价需要两笔新单，100 个股票每秒刷新一次已需 200 笔新单/秒，远超这个公开额度，尚未计撤单。因而“数百合约、毫秒内部反应”的平台目标与“数百 Direct Stocks 持续高频重挂”的外部能力必须分别验收。订单提交是否获得特定交易场所 maker 地位、返佣或报价义务，也不能由 LIMIT 名称推定。

## API 资格、测试环境与后续验证

API 文档和官方 SDK 证明程序化接口存在；这不等于该账户获准使用全部产品、行情权限或做市计划。Stocks 声明接口记录法律接受，且与 API-key 所属账户绑定；本轮未调用。股票和 bStocks 均按地区、产品及账户条件开放。[Account API](https://developers.binance.com/en/docs/catalog/advanced-trading-stocks-trading/api/rest-api/account)、[官方 SDK](https://github.com/binance/binance-connector-go/tree/master/clients/stocks)、[股票 FAQ](https://www.binance.com/en/support/faq/detail/7ae9ef8636e74e8b9c3b625677b83310)。

Spot Testnet 只支持 `/api`，不支持 `/sapi`，因此不能用它验证 Direct Stocks 或股票铸造/赎回；也没有证据表明 bStocks 样本一定在 Spot Testnet 上市。本轮未发现可公开确认的 Direct Stocks 专用模拟环境；“SDK 有 tests”不等于存在对应交易沙箱。[Spot Testnet General Info](https://github.com/binance/binance-spot-api-docs/blob/master/testnet/general-info.md)。

建议后续接入验证只选少量用户指定样本，保留下列待办：

1. 取得官方可核验的 **借入股票/bStocks 本身** 流程、账户资格与样本券源；没有这一证据，不把硬性借券需求标为完成。
2. 分别核验股票 symbol、bStocks assetCode 和 Spot symbol；记录交易权限、精度、时段、代币化 multiplier 与该账户实际支持的订单能力。
3. 确认 Direct Stocks 权威可卖库存、冻结与结算快照接口；在此之前，无法完整实现有状态做市的启动恢复和风控。
4. 只读采样 WS：记录源时间、推送时间、本机接收时间，确认 BBO 覆盖、陈旧判断、断流与订单簿恢复；性能报告区分采样周期、网络时延、内部处理和订单终态。
5. 确认模拟环境；如无产品沙箱，先做录制回放和本地订单状态仿真。任何真实账户权限接受或交易验证应另按用户明确授权的任务进行。

## 来源版本说明

所有链接核查于 2026-09-10；开发文档及 GitHub master 是滚动版本，未声称固定发布版本。主要产品资料：股票操作说明更新 2026-07-20；股票 FAQ 更新 2026-06-08；bStocks FAQ 更新 2026-07-28；bStocks 抵押 FAQ 更新 2026-07-24；FPSL FAQ 更新 2026-08-14；SPCX 官方比较更新 2026-06-29；证券产品条款 v1.4 于 2026-07-20 生效。报告只把官方文字直接支持的内容标为事实，其余明确作为推论或待验证事项。
