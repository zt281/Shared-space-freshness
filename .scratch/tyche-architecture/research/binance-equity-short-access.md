# Binance 美韩股票相关产品的 USDT 开空与 API 能力

核查日期：2026-09-14。范围：官方网页和无需凭据的公开 API；未登录、未签协议、未下单。研究分支 `research/binance-equity-short-access`。用户已明确个人 Binance 账户、接受衍生品、USDT 资金、不另开美元账户；首版仅纳入符合条件目录，可跳过不支持标的，三星与 SK 海力士为样本。

## 结论与产品边界

**Binance USDⓈ-M 股票相关 TradFi 永续是满足条件的首版候选**，但具体采用它尚待用户选择；产品存在和公共 API 可见不等于用户个人账户有权限。

| 产品 | 已核事实 | 对本需求的意义 |
| --- | --- | --- |
| Direct Stocks | 官方说明可用 USDT 等资金购买美国股票和 ETF，具有股份受益所有权 | 本次未找到足够官方证据确认卖出开空及个人 API 条件，不能承诺可用 |
| bStocks | 代币化证券；官方抵押品 FAQ 说明当前不支持借入 | 不能作为已证实的借入卖空路径 |
| 股票 TradFi 永续 | 无到期日、USDT 结算，可建立衍生品空头 | 候选；并非持有股票或借券卖空 |

来源：[Direct Stocks 官方说明](https://www.binance.com/en/blog/markets/3291762588579390744)、[bStocks FAQ](https://www.binance.com/en/support/faq/detail/4f5444780f444bf6b39adbec77ef545a)、[股票永续介绍](https://www.binance.com/en/academy/articles/how-to-trade-stock-perpetual-contracts-on-binance)。不把 Binance Square 普通用户帖子当作官方证据。

## 标的和实时公共核查

官方 2026-06-02 上市公告明确 SKHYNIXUSDT 跟踪 SK Hynix、SAMSUNGUSDT 跟踪 Samsung Electronics，USDT 结算、24/7 交易。[上市公告](https://www.binance.com/en/support/announcement/detail/ed2c6a6160c64eb397b534af90b9d66a)

本次直接读取 [生产 exchangeInfo](https://fapi.binance.com/fapi/v1/exchangeInfo) 返回：

| symbol | status | contractType | quoteAsset / marginAsset | underlyingType |
| --- | --- | --- | --- | --- |
| SKHYNIXUSDT | TRADING | TRADIFI_PERPETUAL | USDT / USDT | KR_EQUITY |
| SAMSUNGUSDT | TRADING | TRADIFI_PERPETUAL | USDT / USDT | KR_EQUITY |
| SKHYUSDT | TRADING | TRADIFI_PERPETUAL | USDT / USDT | EQUITY |
| MSTRUSDT | TRADING | TRADIFI_PERPETUAL | USDT / USDT | EQUITY |
| AMZNUSDT | TRADING | TRADIFI_PERPETUAL | USDT / USDT | EQUITY |
| COINUSDT | TRADING | TRADIFI_PERPETUAL | USDT / USDT | EQUITY |

SKHYUSDT 跟踪美国 ADR，SKHYNIXUSDT 跟踪韩国上市股票，不能合并为同一交易标的。Academy 对韩股 KRW 表述不能被直接当成最新报价换算规则；较新 FAQ 说明 2026-08-07 已应用 USDT/KRW 换算。[SK Hynix 产品对比](https://www.binance.com/en/academy/articles/how-to-trade-sk-hynix-skhy-on-binance)、[TradFi 规则](https://www.binance.com/en/support/faq/detail/fe7dcdf24f1943d98b368f5f9f744398)

以上是时间点快照，不是完整目录、永久上架承诺或韩国交易所全覆盖。实现应读取产品字段、交易状态、过滤器和账户能力交集。

## 开空、API 与账户条件

官方 USDⓈ-M 下单支持 SELL；单向模式 `positionSide=BOTH`，双向模式指定 `SHORT`，双向模式不能发送 `reduceOnly`。据该下单模型推断，从空仓建立空头应使用符合账户模式的 SELL 开仓指令；这不是无需保证金，也不能在已有多头时忽略净仓变化。[交易 API](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/trade)

同一官方交易 API 提供 `POST /fapi/v1/order` 报单、`DELETE /fapi/v1/order` 撤单和查询接口；另有 `POST /fapi/v1/stock/contract` 用于签署 TradFi 协议。已有 API 不等于已签该协议或已获该产品权限。本次未调用签署接口。

行情规则、深度、价格和资金费走 USDⓈ-M 公共市场 API；订单变化用 `ORDER_TRADE_UPDATE`，资金与持仓变化用 `ACCOUNT_UPDATE`，账户流需维护 listenKey、24 小时连接轮换和重连恢复。[市场 API](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data)、[账户流](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/user-data-streams)

**架构推断**：公开 HTTPS/WebSocket 接口允许服务直连，不依赖本地券商 Windows 桌面终端；部署地区网络可达性仍须实测。未找到仅机构可用的股票永续限制，但没有用户地区、账户开通状态和交易权限的证据，故个人账户可用性仍待用户端验证，不以“个人账户”直接判定通过或拒绝。

限流以 exchangeInfo 的 rateLimits、接口权重和响应头为准；429 退避、持续违规可能 418；下单 503 可能执行状态未知，应先查单，避免盲重试。[通用说明](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/general-info)

## 时段、价格与费用

股票永续 24/7 撮合不代表底层股票持续交易。较新 TradFi FAQ 对韩国股票采用 09:00–15:20（UTC+9）常规指数模式，其余时段、周末及节假日为订单簿 EWMA；常规指数依赖行情供应商，休市期间使用订单簿平滑指数。标记价与最新成交价是不同数据；底层休市不能被建模为合约关闭，也不能拿最后一笔底层现货价当作持续更新的价格。[TradFi 规则](https://www.binance.com/en/support/faq/detail/fe7dcdf24f1943d98b368f5f9f744398)

2026-07-14 公告把 SKHYNIXUSDT、SAMSUNGUSDT 资金费改为每 4 小时、上下限 ±0.50%，覆盖上市时每 8 小时的旧规则。本次 [fundingInfo](https://fapi.binance.com/fapi/v1/fundingInfo) 也返回两者 `fundingIntervalHours=4`、cap `0.00500000`；SKHYUSDT 返回 8 小时、cap `0.02000000`。上限不是实际资金费率，费率动态查询，不能假设空头总收钱。[更新公告](https://www.binance.com/en/support/announcement/detail/ea1076c42f754775850044719885d934)

杠杆、保证金档位、交易手续费和公司行为调整须按具体合约与账户读取；本次不冻结参数。持仓收益核算需包含手续费、资金费及可能的公司行为调整；产品接受衍生品不等于已经决定最大杠杆或休市交易策略。

## 验证与未核实事项

[Demo exchangeInfo](https://demo-fapi.binance.com/fapi/v1/exchangeInfo) 本次返回三星、SKHYNIX、MSTR、AMZN、COIN 为 TRADING，但查询样本未见 SKHYUSDT。Demo 对三星与 SKHYNIX 的 underlyingType 返回 HK_EQUITY，与生产 KR_EQUITY 不同，因此 Demo 不能代替生产产品分类、参数或行情行为。官方确认 Demo REST 与 WebSocket 环境；`POST /fapi/v1/order/test` 不进入撮合引擎，不能验证成交、持仓或回报闭环。[环境说明](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/general-info)、[Test Order](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/trade#test-order-trade)

待后续接入验证：用户实际地区与 TradFi 开通状态、Futures API 交易权限、目标 symbol 账户可交易性、Demo 端到端开空/撤单/平仓回报、生产网络和 WebSocket、实时产品参数、休市与公司行为样本。以上是未完成的验证，不是研究已证明的能力。

待产品决策：是否把首版股票相关交易统一限定为 Binance 上账户可交易的 USDT 股票 TradFi 永续，暂缓 Direct Stocks 和 bStocks；如果采纳，是否允许底层股票休市期间新开仓，以及 SK Hynix 不同上市地产品是否都纳入（可由动态目录规则处理）。
