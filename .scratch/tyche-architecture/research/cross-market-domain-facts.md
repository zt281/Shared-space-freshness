# 跨市场账户、合约与持仓字段的官方语义

核查日期：2026-09-14。研究分支 `research/cross-market-domain-facts`。先复用已有 Binance 产品、股票永续、CTP 接入研究，再核查下列第一方接口。未访问凭据、账户或交易；不决定账户数量、展示币种、归属算法。

## 紧凑语义表

“建议”列是架构推断，不是供应商承诺或已确认产品决定。

| 主题 | 已核实事实与来源 | 对 Tyche 的建议 / 边界 |
| --- | --- | --- |
| CTP 身份、资金 | 上期技术指南区分期货公司 BrokerID 和该公司客户 UserID；报单使用 InvestorID。ReqQryTradingAccount 查询投资者资金，包括保证金、手续费、持仓盈利、可用资金。[CTP 指南][ctp] §3.3、§4.5 | 账户身份至少包含环境、接入机构和投资者；连接/API 实例不是资金账户。商品、股指是产品分类，不能推导为两个资金账户；实际账户数量由用户/接入配置确定。当前 SDK 的 AccountID、CurrencyID、业务类型和查询范围仍待核实。 |
| CTP 持仓 | 指南的汇总按合约、方向、开仓日期组织；YdPosition 是昨日收盘静态数量，Position 是当前数量，TodayPosition 为今仓；当前昨仓由汇总 Position 减 TodayPosition 得出。[CTP 指南][ctp] §4.4 | 保存原始持仓分组，不能将 YdPosition 直接当作当前可平昨仓。指南较旧，“仅上期所分今昨”的描述不作为当前全部交易所规则；SHFE/INE 等目标市场分桶、平今/平昨、冻结及投保标志须以目标 SDK 和柜台验收。 |
| Binance 资金与保证金 | Futures 账户接口分别提供余额、可用余额、保证金字段及 Multi-Assets Mode；Options 有独立 marginAccount 查询，含按 asset 的 equity、available、initialMargin 等。[Futures 账户][fa]、[Options 账户][oa] | 登录账户、产品账户/钱包、保证金范围、币种分开表示。不能把接口余额直接相加：是否资金重叠须核对实际账户模式；同为 USDT 也不证明可相互提供保证金。 |
| Futures 持仓 | Futures 支持 One-way 与 Hedge 模式；持仓方向使用 BOTH 或 LONG/SHORT。当前接口说明 UM/CM 共享持仓模式，任一侧已有委托或仓位会阻止模式切换。[Futures 交易][ft] | 原始方向保留，净敞口可派生。模式是账户能力/配置，不由策略随意切换；净数量不能替代双向仓位及保证金信息。 |
| Options 持仓 | Options position 返回 side，quantity 正数为多、负数为空；订单有 clientOrderId，成交有 orderId、fee、realizedProfit。[Options 交易][ot] | 不套用 Futures Hedge 配置。字段能表达空仓不证明个人账户获准卖出开仓；权限仍按已定普通账户范围和实际能力验收。 |
| 合约与行情源 | Futures exchangeInfo 按 symbol 返回合约类型、资产与规则；Options 额外给到期、行权价、CALL/PUT、underlying、unit、settleAsset。[Futures 市场][fm]、[Options 市场][om] | 合约标识建议由交易场所/产品命名空间/原生代码确定；环境命名空间必须隔离实盘与仿真。行情来源、连接、快照版本另行标识，同一合约的多个行情源不必成为多个经济合约。 |
| 股票永续身份 | 已有研究核实 SKHYUSDT（美国 ADR）和 SKHYNIXUSDT（韩国上市股票）不同；生产与 Demo 的分类存在差异。[既有证据](binance-equity-short-access.md#标的和实时公共核查) | 不用“公司名称”合并合约；不同环境目录分别加载。共同标的关系可链接，永续不能等同股票所有权。 |
| 数量、价格、乘数 | Futures 提供 PRICE_FILTER、LOT_SIZE 等过滤器；Options 提供 unit、到期时间与价格数量规则。[Futures 市场][fm]、[Options 市场][om] | tick、数量步长、展示小数位、合约乘数、报价/结算币种分别表达。不能把所有数量称为股票“股数”，不能只按小数位验证步长。CTP 当前 SDK 的 PriceTick/VolumeMultiple 及产品单位需验收，本轮未核当前字段合同。 |
| 交易日、时间 | CTP 按交易日进行结算确认；指南明确仿真资金及成交不是实盘。Binance Options 给 UTC 时间及 expiryDate；股票永续可 24/7 交易而底层股票有休市。[CTP 指南][ctp] §4.3、§8；[Options 市场][om]；[既有股票时段证据](binance-equity-short-access.md#时段价格与费用) | 保留交易日、事件时间、接收时间、时区及日历来源；不以电脑自然日推导全部交易日，也不以底层休市判定永续不可交易。CTP 夜盘 TradingDay/ActionDay 跨周末/节假日规则仍需目标通道样本。 |
| 策略、手工和外部归属 | 已查通道提供账户持仓与订单/成交标识；这些接口未提供 Tyche 自定义策略的持仓账。[CTP 指南][ctp]、[Futures 交易][ft]、[Options 交易][ot] | 策略/手工归属是 Tyche 内部账，需要持续保存订单关联。无法关联的外部订单、初始持仓必须显式表达未归属；不能自动宣称属于某个策略。外部平仓如何冲减、内部转移及盈亏成本法仍需用户决策。 |

## 核查限制与接入验收

- CTP 引用为上期技术原文、期货公司托管的历史指南；读取成功，未用第三方教程、CTP Mini 或交易所直连接口替代标准 CTP 当前合同。当前 SDK 的资金币种字段、合约乘数、投保及今昨分组、夜盘日历留作接入验收；不因此冻结领域字段。
- Binance 引用为当前开发文档；实际个人账户 Futures/Options 权限、保证金模式、钱包是否有重叠范围，以及切换模式条件尚未用账户验证。研究没有给用户选择单向/双向或全仓/逐仓。
- 验收需包含：同一账户两个策略反向成交；外部终端开平仓；CTP 今仓转昨及部分平仓；Futures 净/双向样本；Options 买入后部分卖出；重复和补发成交去重；原币种资金查询、保证金范围去重；实盘/Demo 同名合约隔离；夜盘及到期跨日；规则变化后价格数量校验。以上是未来行为样本，不是本次已跑测试。
- 归属账只能解释交易贡献。原币种资产折算是展示视图，不能产生实际跨账户可用资金；汇率来源、时间及缺失处理尚需设计。研究不选择默认展示币种。

[ctp]: https://www.eastmoneyfutures.com/software/9809db08-c8cb-4cc4-b631-8a16f0c2dfb9/0f757a06-10a5-48c2-817e-362b42202b51/f3ec4355-a448-45d7-bd51-3124d046092a/CTPcdg_ch.pdf
[fa]: https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/account
[ft]: https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/trade
[fm]: https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data
[oa]: https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-options/api/rest-api/account
[ot]: https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-options/api/rest-api/trade
[om]: https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-options/api/rest-api/market-data
