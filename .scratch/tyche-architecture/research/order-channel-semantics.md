# CTP 与 Binance 订单通道语义

核查日期：2026-09-14。供「订单、风控和恢复语义」决策使用。复用 [CTP 接入研究](ctp-qmt-access.md) 与 [Binance 做市能力研究](binance-crypto-market-making.md)，并重新查阅下列第一方资料。未访问账户、凭据或发送交易；以下工程建议尚待用户决定和接入验收。

## 影响行为的事实

| 范围 | 官方事实与来源 | 对 Tyche 的工程推论 |
| --- | --- | --- |
| CTP 请求、订单、成交 | 上期技术开发指南第 28–29、35、37 页：同步返回值表述发送结果；`OnRtnOrder` 回报多阶段状态，包括未知、接受、拒绝、撤销、成交；`OnRtnTrade` 表达具体成交，二者可能有时间差。订单关联包括 `FrontID+SessionID+OrderRef` 和 `ExchangeID+OrderSysID`。[供应商指南，由期货公司托管][ctp] | SDK 返回 0 不得显示交易所已受理或成交；持久化原始标识及映射，不把重启后的 OrderRef 单独当全局键。成交记账与订单累计量核对，避免重复增加持仓。 |
| UM / Options 未知结果 | 两产品 General Info 均将特定 503 超时列为执行状态未知，可能成功；UM 明示先查 WS/订单再决定重试。明确失败的 503 文案另有分类。[UM][um-info]、[Options][op-info] | 区分已发送、明确拒绝、结果未知；未知期间保留可能风险占用，同一交易意图不盲目发新订单。共享空间发布成功也不等于交易所已执行。 |
| UM 查询、改单、批量、保护 | Query Order 可用订单或客户标识；新客户号只要求在未结订单间唯一。部分无成交取消/过期单 3 天后不可查，其余订单 90 天；LIMIT 改单重新排队，数量不大于已成交量等情形会撤单。批量并发且撮合顺序不保证。倒计时按 symbol 撤全部挂单，官方示例 30 秒续 120 秒，检测约 10ms 并要求留余量。[UM Trade][um-trade] | 客户号不是永久幂等保证；本地留存证据。批量逐单处理结果，禁止视作双边原子成交。共享账户中原生全撤可能影响其他策略；不能用停止续期表达只停一个策略。 |
| Options 查询及历史 | 单笔查询可用 `orderId` 或 `clientOrderId`；客户号不能与未结单重复；已结束订单历史接口写明仅 5 天。接口分别提供新单、批量、撤单与成交查询。[Options Trade][op-trade] | 查无记录不等于从未接受。持久化回报、成交和核对位置；超出历史窗口或无法闭合证据时，相关交易路径继续阻断。未核实普通 Options 原生改单的完整语义，不能套用 UM。 |
| Options 服务器保护权限 | 官方 FAQ 将 MMP 与 countdown 全套列入做市商专用；MMP 触发撤 MMP 订单并拒新 MMP 单。[API FAQ][op-faq] | 普通个人账户已有 API 不代表保护可用；能力至少分已验证可用、不可用、未知。普通卖出开仓权限与 MMP 分开验收。 |
| Options countdown 续期与范围 | 按 underlying，缺心跳撤该 underlying 的 MMP 及非 MMP 单；触发后拒新单，直到心跳恢复或关闭。心跳响应只列续期成功的 underlying。[MM endpoints][op-mm] | 心跳 HTTP 成功不能代表全部续期成功；逐项检查。其作用域不是策略，必须同账户协调。保护恢复不能绕开 Tyche 的依赖、版本、订单、持仓恢复条件。 |

## 建议纳入订单状态与恢复契约

以下是工程推论，不是通道保证，也不是替用户完成尚未回答的产品决定。

- 撤单请求与撤单确认分开；已部分成交的订单即使余量撤销，成交仍保留。撤单途中继续接收成交；撤单拒绝或超时先查询，不能把剩余量直接释放并换单。
- 请求编号、交易意图编号、通道订单编号、成交编号分开持久化。恢复从本地日志与通道查询、私有回报交叉核对；成交去重键必须包含环境、账户、产品/交易所等作用域，并用实际 SDK/流文档确认其唯一性，不能仅按时间戳去重。
- 「共享数据版本追平」和「交易副作用核对完成」是两个条件。重放共享命令不能自动重发交易请求；查询有保留期限，不提供无限事件重放保证。
- 本次第一方资料未提供跨节点、跨交易所 exactly-once 或双边原子成交保证。跨腿先成交、另一腿拒绝/未知属于必须设计的业务状态；补单、对冲或平仓属于新的风控交易意图，不能假定撤单可以回滚成交。
- 本地停止发单只能阻止 Tyche 后续发送；网络断开后不能保证已有挂单被撤。CTP 目标柜台的断线自动撤单、原生改单/报价、批量以及特殊做市权限尚未核实，不能宣称不存在，也不能默认可用。

## 最小接入验收

1. 锁定目标 CTP 标准 SDK 与柜台版本，复核同步失败、异步拒绝、未知订单、部分成交、撤单竞争及请求/成交标识作用域。所查指南为旧版，不以其旧交易所覆盖、费用或状态枚举推断现行全部能力；不拿 CTP Mini 或交易所会员 API 代替标准 CTP。
2. 在适当模拟环境覆盖发送前崩溃、发送后未收回报崩溃、回报重复/乱序/缺口、重连与跨交易日；验证持久化恢复不会重发未知交易或重复记成交。缺口无法闭合须维持阻断并可诊断。
3. UM、Options 分别确认客户号生成/复用规则、单笔与历史查询窗口、分页及限流、成交唯一键、回报订阅恢复。一次查无订单不能单独证明可安全重试；特别覆盖完全成交后客户号再用风险。
4. 逐产品、账户、symbol/underlying 回读保护配置并测试续期缺失与部分成功。验证服务器保护对其他策略/外部客户端挂单的影响；普通 Options 无特殊授权时不得显示保护已启用。
5. 验证 UM 改单重排队、部分成交导致撤单、批量混合成败；Options 和 CTP 未确认能力保持未知。测试覆盖单腿成交另一腿失败，验收依据用户最终选择的残余风险策略。

## 来源与限制

CTP PDF 浏览工具抓取失败，但已通过 HTTPS 下载并 `pdftotext` 阅读上述页码；未依赖第三方博客。Binance 文档读取于本日，实施时需冻结契约快照并用账户/环境验证。未做性能或交易验收，未承诺成交、撤单成功或精确触发时限。

[ctp]: https://www.eastmoneyfutures.com/software/9809db08-c8cb-4cc4-b631-8a16f0c2dfb9/0f757a06-10a5-48c2-817e-362b42202b51/f3ec4355-a448-45d7-bd51-3124d046092a/CTPcdg_ch.pdf
[um-info]: https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/general-info
[op-info]: https://developers.binance.com/en/docs/products/derivatives-trading-options/general-info
[um-trade]: https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/trade
[op-trade]: https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-options/api/rest-api/trade
[op-faq]: https://www.binance.com/en/support/faq/detail/fe0be251ac014a8082e702f83d089e54
[op-mm]: https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-options/api/rest-api/market-maker-endpoints
