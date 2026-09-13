# Binance BTC/ETH 期权与 USDT 永续的做市及账户能力

核查日期：2026-09-10。范围：BTC/ETH 加密期权、BTCUSDT/ETHUSDT USDT 本位永续；一个 Binance 账号，普通保证金作为初始假设，实际模式待核实。用户已确定期权卖方必须能够在没有已有多头时 SELL 开仓，并接受启动前验证权限。本报告只核查公开官方资料，没有访问账号、获取凭据、切换模式或发送订单。

## 结论

**公开产品规则已支持合格普通用户对 BTC/ETH 期权卖出开仓，不能再笼统写成“只有做市商可以卖期权”。** BTC 于 2025-08-04、ETH 于 2026-01-16 向所有符合产品准入条件的 Options 用户开放卖出开仓，需启用 Options 的 `Long & Short Sell` 模式；公告仍注明地区限制。该事实不能证明用户当前账号已经开通。[BTC 公告](https://www.binance.com/en/support/announcement/detail/e80dd709384244719e653c1e9d1541c2)、[ETH 公告](https://www.binance.com/en/support/announcement/detail/7372ff010d914e84b9fd994f849478cd)

普通用户的卖出开仓能力、官方做市项目资格、MMP 权限和断线自动撤单权限应分别记录。2026-05-27 更新的官方 API FAQ 仍将 Options MMP 和 countdown cancel 全套接口列入做市商专用能力；因此首版不能把这两项当作普通账户已有保障。[Options API FAQ](https://www.binance.com/en/support/faq/detail/fe0be251ac014a8082e702f83d089e54)

## 已核实的公开事实

### 1. 期权买入、卖出平仓、卖出开仓是不同能力

2026-07-28 更新的卖空 FAQ 明确解释：short-selling 功能允许用户卖出尚未持有的期权，当前面向 BTC、ETH；文档分别列出 Buy to Open、Buy to Close、Sell to Open、Sell to Close 的保证金处理，卖出开仓要求保证金，卖出平仓的订单初始保证金为零。因而“SELL 请求存在”或“卖出已有多头成功”都不足以验证本项目要求。[Short-Selling FAQ](https://www.binance.com/en/support/faq/detail/1ceb77f837344e3085ecf98d9a6a8097)

2026-01-16 公告确认当前 Binance Options 以 USDT 计价和结算。本文仅讨论 BTC/ETH 加密期权；该公告对其他标的另列限制，不能将它们与 BTC/ETH 权限合并判断。[ETH 卖出开仓及平台升级公告](https://www.binance.com/en/support/announcement/detail/7372ff010d914e84b9fd994f849478cd)

Options 错误码包含 `-5010 NOT_ENOUGH_POSITION`、`-6005 IS_NOT_MARKET_MAKER`、`-6036 NO_PERMISSION_TO_CHANGE`，以及最大空头持仓、挂单数量等拒绝类型。这说明接口需要处理具体能力和约束拒绝；单凭旧错误码列表，不能推翻较新的 BTC/ETH 普通用户卖出开仓公告。[Options Error Codes，读取于 2026-09-10](https://developers.binance.com/en/docs/products/derivatives-trading-options/error-code)

### 2. 普通保证金与组合保证金的边界

卖空 FAQ 说明默认 Options 使用 cross margin，**不会在 Options、Futures、Margin 账户之间做组合保证金或风险净额抵扣**。其所述 Portfolio Margin SPAN 面向 Options Enhanced Program 用户，当前仅经 API 使用。这里的 cross margin 不能解释成“同一登录账号下所有产品共用可用保证金”。[Short-Selling FAQ，更新于 2026-07-28](https://www.binance.com/en/support/faq/detail/1ceb77f837344e3085ecf98d9a6a8097)

现行公开资料中有三个必须分开的层次：

| 层次 | 已核实的含义 | 对首版的影响 |
|---|---|---|
| 普通产品账户 | Options 与 USDⓈ-M Futures 分别有产品 API；Options 默认无跨产品风险净额抵扣 | 可以使用同一 Binance 登录身份，但资产、可用余额和风险不能直接合并扣减 |
| Portfolio Margin | 独立 API 基址 `https://papi.binance.com`，UM 交易接口是 `/papi/v1/um/order` | 若实际开通 PM，不能只替换普通账户名称，必须核对交易、账户查询和回报路径 |
| Options SPAN / Enhanced 能力 | FAQ 指定为专门准入能力，并非普通账户 cross margin 的别名 | 首版不预设已拥有，不把“普通 PM”与“Options SPAN”当同一个开关 |

表中普通账户边界来自 [Options FAQ](https://www.binance.com/en/support/faq/detail/1ceb77f837344e3085ecf98d9a6a8097)；PM 基址来自 [PM General Info](https://developers.binance.com/en/docs/products/derivatives-trading-portfolio-margin/general-info)，具体订单路径来自 [PM Trade API](https://developers.binance.com/en/docs/catalog/advanced-trading-derivatives-trading-portfolio-margin/api/rest-api/trade)。Portfolio Margin Pro 还有自己的官方文档类别；本票不展开其所有端点，尤其不推定用户具备其权限。[PM Pro General Info](https://developers.binance.com/en/docs/products/derivatives-trading-portfolio-margin-pro/general-info)

### 3. 双边报价不等于双向持仓模式

USDⓈ-M 的三个设置作用域不同：`marginType` 为逐合约的 `ISOLATED` / `CROSSED`；`dualSidePosition` 选择 Hedge / One-way，作用于全部合约；`multiAssetsMargin` 选择 Single-Asset / Multi-Assets，作用于所有合约。订单在 One-way 使用 `positionSide=BOTH`；Hedge 必须显式提供 `LONG` 或 `SHORT`，且不能传 `reduceOnly`。[USDⓈ-M Trade API，读取于 2026-09-10](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/trade)

Options 的 `Long & Short Sell` 是卖出开仓能力模式；上述 Futures Hedge / One-way 是持仓记账模式。它们由不同产品文档定义，因此不能映射成一个通用的“允许双边”布尔量。[Options 升级公告](https://www.binance.com/en/support/announcement/detail/7372ff010d914e84b9fd994f849478cd)、[USDⓈ-M Trade API](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/trade)

### 4. 做市资格、MMP、断线保护

2024-04-05 的官方公告明确指出 **Options Enhanced Program 替代原 Options Market Maker Program**。2026-01-16 公告给出的申请条件为过去 30 天交易额超过 100M USDT、资产超过 1M USDT；申请资格不是已授予的交易权限。[Enhanced Program 公告，含后续修订说明](https://www.binance.com/en/support/announcement/detail/5c4089a8fa544a20b1b9347e330aeefd)、[2026-01-16 公告](https://www.binance.com/en/support/announcement/detail/7372ff010d914e84b9fd994f849478cd)

较旧的 [2023 年 MM 公告，修订于 2024-01-23](https://www.binance.com/en/support/announcement/detail/23b580ab0b224347ae50e68bf76647f7) 仍会出现在搜索结果中，包含 100k USDT 资产门槛。它不能用作本项目当前卖出开仓准入或 Enhanced 申请门槛。需按资料日期及明确替代关系解释，不能将不同计划的数字拼成一个条件。

| 能力 | 官方定义或边界 | 普通账号能否直接预设 |
|---|---|---|
| BTC/ETH 卖出开仓 | 启用 Options Long & Short Sell 后，允许无已有期权多头卖出 | 公开规则支持；具体账号仍需核实 |
| Options MMP | 超过数量或 Delta 等阈值后撤销标记为 MMP 的订单，并冻结新 MMP 订单 | 不能预设；官方定位为 Options 做市商保护 |
| Options countdown cancel / kill switch | 缺少心跳后按 underlying 撤销 MMP 和非 MMP 订单；触发后新单会被拒绝，直至心跳恢复或关闭该功能 | 不能预设；API FAQ 列入做市商专用接口 |
| Futures countdown cancel | `/fapi/v1/countdownCancelAll` 按 symbol 设置倒计时撤单 | 官方将其列为普通签名 TRADE 端点；实际账号与环境仍需验收 |

MMP 的保护对象和冻结语义来自 [MMP FAQ，更新于 2026-01-02](https://www.binance.com/en/support/faq/detail/0b81ad7d8ae54d3f8d29a1ce66764fa1)；Options 专用权限及 kill switch 语义来自 [Options API FAQ](https://www.binance.com/en/support/faq/detail/fe0be251ac014a8082e702f83d089e54)；Futures 倒计时接口来自 [USDⓈ-M Trade API](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/trade)。本表不把本地“停止发单”描述成交易所端撤单，也不把 Options 权限结论外推给 Futures。

### 5. 所选产品的 API 与模拟环境

| 产品 / 路径 | 生产侧已核实资料 | 测试环境证据与限度 |
|---|---|---|
| BTCUSDT / ETHUSDT 普通 USDⓈ-M | REST 基址 `https://fapi.binance.com`，订单 `/fapi/v1/order`；行情与私有回报另有 WebSocket 通道 | General Info 指定 REST `https://demo-fapi.binance.com`，WS `wss://demo-fstream.binance.com`；本次未做连通或交易测试 |
| BTC / ETH 普通 Options | REST 基址 `https://eapi.binance.com`；`/eapi/v1/order`、批量订单、撤单、持仓与成交查询；行情和私有数据由对应流提供 | **Options General Info 当前也明确写 `https://demo-fapi.binance.com`**，并给出 `wss://demo-fstream.binance.com/public/`、`/market/`、`/private/`；文档称测试网 key 可用于期权测试，但本次未核实实际期权合约、路径和卖出开仓权限 |
| PM UM | `https://papi.binance.com` 下的 `/papi/v1/um/order` 等 | 本票未核实适用 PM / Options SPAN 的模拟账户及环境；不能套用普通 Futures 测试结论 |

来源：[USDⓈ-M General Info，页面标注最后修改 2026-09-10](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/general-info)、[Options General Info，同日版本](https://developers.binance.com/en/docs/products/derivatives-trading-options/general-info)、[Options API FAQ](https://www.binance.com/en/support/faq/detail/fe0be251ac014a8082e702f83d089e54)、[PM General Info](https://developers.binance.com/en/docs/products/derivatives-trading-portfolio-margin/general-info)。这里只记录官方公布地址，不依据 `eapi` 命名自行构造测试 URL，也不将“文档存在”标为“已通过期权模拟交易”。

Options 当前私有流文档给出的生产连接为 `wss://fstream.binance.com/private/ws/<listenKey>`；listenKey 有效期 60 分钟、连接寿命 24 小时，订单事件为 `ORDER_TRADE_UPDATE`。因此也不能从 REST 的 EAPI 名称猜测私有 WebSocket 主机。[Options User Data Streams，页面标注最后修改 2026-09-10](https://developers.binance.com/en/docs/products/derivatives-trading-options/user-data-streams)

USDⓈ-M 文档区分 503 中的“执行状态未知”与明确失败：前者可能已经成功，应先查私有回报或订单状态再决定重发。它是做市撤改单验收必须保留的情况。[USDⓈ-M General Info](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/general-info)

### 6. 一个账号仍然需要多个明确的配额与配置作用域

2026-06-10 发布的 UM/CM 整合通知写明 2026-06-24 起逐步实施、6 月 30 日全面生效：UM 与 CM 共用 `dualSidePosition`，任一侧存在挂单或持仓时不能切换；共用 IP 请求权重 2400/min，以及账号订单量 1200/min、300/10s。首版虽然只做 USDT 永续，账号其他 CM 活动仍可能占用该配额或阻止切换。[UM/CM 整合通知](https://developers.binance.com/en/docs/products/derivatives-trading-coin-futures/Important-CM-UM-Integration-Notice)

Options General Info 要求根据 `/eapi/v1/exchangeInfo` 的 `rateLimits` 以及响应头处理权重和订单限流；请求限流基于 IP，不是 API key。没有查到本票所读资料明确把 Options 的 EAPI 配额也并入上述 UM/CM 池，因此不能凭同一账号或同一 IP 就合并或拆分所有池。[Options General Info](https://developers.binance.com/en/docs/products/derivatives-trading-options/general-info)

## 工程推论：建议纳入架构约束

以下为根据上述事实形成的实现建议，不是已完成的账号验证。

1. **用户本轮 Q56 已选择：普通账户为首版，组合保证金先做模式识别与接口预留。** 这是用户的范围选择，不是交易所的产品限制。普通账户接入路径为 USDⓈ-M + Options。账号配置应显式记录实际 account mode、产品开通状态、Options 卖出开仓、MMP、Options countdown cancel、Futures position mode、margin type、multi-assets mode。能力可用、不可用、未核实至少是三种状态。
2. **期权 SELL 开仓必须是启动条件。** 将“无已有多头可 SELL 开仓”单独列入准入校验；只有卖出平仓权限或结果未知时，不启动要求双边开仓的期权策略。不能通过代码配置自行宣称交易所已授权。
3. **持仓模式不由报价方向自动决定。** One-way / Hedge 应遵照账户实态和策略需求显式映射。仅“买卖两侧都报价”并不足以要求把账号改为 Hedge；启动过程先核对，不能为单个策略自动切换整个账号模式。
4. **经济风险可以统一展示，保证金扣减按真实范围执行。** 可以汇总期权与永续 Delta 等风险，但普通账户模型不能因组合 Delta 接近零而释放交易所不承认的保证金；余额和保证金保留产品及资产维度。
5. **服务器保护作为可选已验证能力。** MMP 与倒计时撤单应各有状态、作用域与生效回读；MMP 仅覆盖标记订单。若策略必须依赖交易所断线撤单而账号不支持，保留启动阻断，不能用本地看门狗宣称满足同一保证。
6. **共享发送治理。** BTC 与 ETH 永续使用同一账号订单预算；同 IP 的流量共享对应请求预算。按产品和文档所定义作用域维护计数，保留撤单余量；不让多个策略各自以为拥有完整限额。
7. **模拟验收与生产准入分别留证据。** Demo 验证适配器和回报处理，生产账号的产品开通、卖出开仓、保护权限和限额需独立核验。测试网通过不能代替生产权限证据。

## 未确定事项与最小后续核验

| 未确定事项 | 为什么影响首版 | 后续应记录的证据 |
|---|---|---|
| 用户真实账号是普通、PM 还是其他模式 | 决定资产、下单与私有回报路径 | 账号模式与产品侧账户查询相互匹配；本次未读取 |
| BTC/ETH Options 卖出开仓已启用且对 API 生效 | 用户明确要求无多头 SELL 开仓 | 产品模式、API 授权及交易所可验证的准入结果；不能用 BUY / sell-to-close 代替 |
| MMP 和 Options countdown cancel 是否获授 | 影响策略依赖的交易所端保护 | 能力查询或平台确认，再在合适测试环境验收；不是请求已发出就算开启 |
| Options demo 的真实可用合约和开空能力 | 官方公布地址与生产命名不同且本次未实测 | 在公布环境核实合约、REST/WS 路由、回报及负持仓能力，不猜地址 |
| 普通账户 Futures 的 margin / position / multi-assets 配置 | 影响订单字段和共享资金模型 | 启动回读与本地配置一致；不在运行中暗自切换 |
| 账号配额、挂单和空头仓位限制、实际手续费 | 决定可部署报价数量及频率 | 产品规则、账号规则及响应头快照；不能用某个做市计划宣传额度作为默认值 |
| Options SPAN 与其他 PM 路径的实际交易能力 | 用户 Q56 选择首版仅识别与预留，未纳入实际交易支持 | 将来扩大交易支持范围时再开独立核验票 |

本票已经回答所选 BTC/ETH 产品的公开卖出开仓资格及普通保证金边界；剩余事项是具体账号和模拟环境验收，公开资料不能替代。规则页面会更新，实施时应保存实际采用的文档日期和接口契约快照。
