# CTP 与 QMT 接入边界调研

调研日期：2026-09-10。用途：为 Tyche 的架构设计与决策地图提供事实依据；不构成已选定的实现方案。

用户背景：个人多账户，手工与自动交易并存；C++ 后端、Windows Electron/TypeScript/Vue 多屏界面；可部署 Linux/Windows 独立后台；数百合约、至少十几个策略，涉及期权做市、期货做市和跨市场套利。

## 结论表

| 问题 | 核实结果 | 对框架的约束 |
| --- | --- | --- |
| CTP 能否使用 C++？ | 可以。上期技术《CTP 客户端开发指南》使用 C/C++ 示例并区分行情、交易接口；SDK 提供 Windows/Linux 版本。[CTP 开发指南][ctp-guide]、[SimNow API 下载][ctp-download] | 可规划原生 C++ CTP 适配器；具体编译器、架构、动态库与柜台版本仍需锁定。 |
| CTP 能否覆盖中国期货期权？ | 官方下载按期货期权、股票期权、CTP Mini 等产品分别发布；SimNow 展示六所期货以及不同覆盖范围的期权仿真服务。[API 下载][ctp-download]、[SimNow 产品服务][simnow] | 本项目“CTP 期货期权”不能混同证券股票期权接口，也不能把标准 CTP 与 CTP Mini SDK 混用。 |
| CTP 行情与交易是否同一个连接？ | 开发指南区分行情和交易接口；期货公司为二者提供不同前置地址/端口。[CTP 开发指南][ctp-guide]、[南华认证指南][ctp-auth] | MD（行情）、TD（交易）分别管理登录、连接健康与恢复。 |
| 下载 SDK 后能否直接实盘？ | 不能据此认定。期货公司认证流程涉及 AppID、对应授权码和测试；终端采集规范还区分直接接入与中继模式。[南华认证指南][ctp-auth]、[接入认证技术规范][ctp-terminal] | 接入资格、软件认证、账户权限和网络拓扑必须形成明确配置与验收项。 |
| QMT、MiniQMT、XtQuant 如何区分？ | QMT 是交易终端产品；极简模式提供 MiniQMT 接入端；XtQuant 是 Python 库，含 xtdata 行情模块和 xttrader 交易模块，交易前须启动客户端。[迅投快速开始][qmt-start]、[迅投连接 FAQ][qmt-faq] | 策略引擎与券商客户端有不同生命周期；不能由 Electron 窗口是否存在决定接入端是否运行。 |
| QMT 能否坚持纯 C++ 接入？ | 已核实的公开可用文档是 XtQuant Python API。本次未获得供应商面向该用户/券商的原生 C++ SDK、支持矩阵及授权承诺。[迅投快速开始][qmt-start] | **C++ 接口可获得性待确认，不能断言其不存在。** “C++ 核心 + 极薄 Python 接入桥”只能作为待用户选择的候选。 |
| QMT 能否放在 Linux 无界面服务器？ | 券商公开发行的是 PC 客户端；迅投连接指南要求客户端极简模式登录及本机 userdata_mini 路径。所查资料没有承诺 Linux 无界面交易部署。[光大软件下载][qmt-broker]、[迅投连接 FAQ][qmt-faq] | 当前应预留 Windows 接入节点；Windows Server、无人值守启动、注销/RDP 断开后的行为需供应商确认与实测。不能将“未核实 Linux”写成“所有迅投产品永久不支持 Linux”。 |
| QMT 权限和测试是否通用？ | 官方 FAQ 明确函数下单权限需券商开启；交易文档说明模拟环境不支持市价报单。[迅投连接 FAQ][qmt-faq]、[XtQuant 交易文档][qmt-trader] | 有 QMT 客户端/行情权限不等于拥有 MiniQMT 自动下单权限；测试环境能力要逐券商确认。 |

## 接入限制与证据边界

### CTP

- **版本必须成套验证。** 官方下载区说明部分升级包仅含 traderapi，行情库或采集库须另取；新功能与柜台版本相关。生产包、评测包不能随意替换，不在设计阶段指定未经目标期货公司确认的“最新版本”。[SimNow API 下载][ctp-download]
- **登录与中继认证不同。** 技术规范中的 `ReqAuthenticate()` 使用 AppID 和期货公司分配的授权码；中继模式另涉及终端信息上报及权限。Tyche 是否属于直接终端或中继，需结合实际部署交期货公司确认；不能直接套用面向操作员的上报方式。[接入认证技术规范][ctp-terminal]
- **有仿真入口，不能当成交质量证明。** SimNow 提供模拟交易及 API 测试环境；其第二套环境不提供结算等完整服务。期货公司还可能要求先用评测版本测试，再用生产版本对接仿真环境复验。[SimNow 产品服务][simnow]、[南华认证指南][ctp-auth]

### QMT / MiniQMT / XtQuant

- **交易客户端是运行依赖。** `XtQuantTrader(path, session_id)` 使用客户端数据目录与会话号，连接后按账户订阅交易回报。数据目录、会话号、账户与券商实例必须显式绑定；文档中的多种账户类型不代表每个券商对个人都开放。[XtQuant 交易文档][qmt-trader]
- **重连存在供应商约束。** 官方 FAQ 提示相同 session 的两次 Python 进程连接需间隔超过三秒；缺少对应下单队列可能是函数下单权限未开通。应据此制定恢复与权限诊断流程，不能用无限快速重试掩盖状态。[迅投连接 FAQ][qmt-faq]
- **行情与交易授权不能合并理解。** 官方 FAQ 还介绍带 token 的 xtdatacenter 行情服务；这不能证明可以绕过 MiniQMT 完成交易。交易路径仍按 xttrader 的客户端依赖评估。[迅投连接 FAQ][qmt-faq]、[迅投快速开始][qmt-start]
- **数百合约需要选择订阅方式。** xtdata 官方建议单股订阅数量不超过 50，订阅较多时使用全推；全推提供合约最新切面，不等价于完整逐笔订单流。L2 函数的历史存储也有约束。[XtQuant 行情文档][qmt-data]
- **模拟的含义必须写清楚。** 大 QMT 的模型“模拟模式”只产生策略信号，不发出委托；这与对接模拟柜台不同。XtQuant 模拟环境的市价报单限制也意味着仿真通过不能覆盖所有实盘订单类型。[QMT 内置 Python FAQ][qmt-inner]、[XtQuant 交易文档][qmt-trader]

## 对 Tyche 架构的影响（推断，待决策）

1. **部署保留异构网关边界。** C++ 核心可部署于 Linux 或 Windows；CTP 原生网关与候选 Windows QMT 网关分别接入。若确认可获得合适的 C++ QMT SDK，可替换桥接实现而保持领域接口稳定。该候选仍需用户接受 Python 例外和期货公司认可实际拓扑。
2. **网关抽象须暴露能力。** 统一订单、撤单、成交、账户状态的共同部分，同时保留订单类型、开平标志、行情深度、原生报价、认证及环境能力；不要用“接口有字段”替代“账户已获权限”。
3. **后端继续运行包含供应商进程。** Electron 退出不应终止策略、订单管理和风控；QMT 通道还依赖 MiniQMT。连接恢复必须先核对委托、成交和持仓，再判断是否恢复策略；请求超时不能直接等价为订单失败或自动重发。
4. **延迟需要分段测量。** 已查资料不足以保证数百合约和十几个策略的实盘毫秒指标。后续分别定义行情接收→策略计算→风控→SDK 提交、柜台回报、跨主机传输和 UI 显示延迟；QMT Python 桥与网络额外开销须用原型测量。
5. **做市与套利能力须逐通道验收。** 是否拥有原生双边报价、批量撤单、报撤单速率、做市相关权限和足够行情粒度，均不能从“支持期权”推导。先确认交易能力，再确定策略调度、风险预算和连接共享方式。

## 待用户、期货公司或券商确认

- 首批 CTP 期货公司与 QMT 券商分别是哪家？每个资金账户已开通哪些产品、API/极简模式和自动下单权限？无需提供密码、授权码或完整账号。
- QMT 若只能取得公开 Python API，是否接受 Windows 上的薄接入桥，C++ 继续承担订单、风控、策略和定价核心？若必须纯 C++，由供应商提供可交付 SDK、ABI、维护政策与个人授权条件。
- 目标 Windows 客户端/Server 版本、MiniQMT 的启动登录方式、是否允许服务器/虚拟机、注销与 RDP 断开行为、多客户端并存及同账户多会话规则是什么？
- CTP 软件 AppID/授权流程、直接终端或中继认定、采集库部署、仿真/生产 SDK 组合、支持的 Linux 发行版与编译工具链是什么？
- 两类接入方的模拟账户申请、测试时段、订单类型差异、行情 L1/L2 权限、订阅与报撤单限制、连接恢复及结算时段行为是什么？
- “期权做市/期货做市”是普通账户持续双边挂单策略，还是需要交易所做市商身份及专用报价接口？“毫秒级”具体约束内部响应还是端到端柜台回报，统计口径为 p99 还是其他分位？

## 调研限制

仅查阅公开第一方资料，未下载大型 SDK、未登录交易账户、未测试网关或测量延迟。SimNow 部分页面和部分 PDF 直接抓取超时，对应事实来自搜索引擎返回的该官方页面/PDF 正文索引；旧开发指南只用于稳定的接口结构，不能作为 2026 年兼容性承诺。南华旧流程页面用于说明认证与环境区分，不能将其历史地址和时段视为目标期货公司的现行配置。未把第三方教程或供应商论坛普通用户发帖作为 C++/Linux 支持结论的依据。

[ctp-guide]: https://www.eastmoneyfutures.com/software/9809db08-c8cb-4cc4-b631-8a16f0c2dfb9/0f757a06-10a5-48c2-817e-362b42202b51/f3ec4355-a448-45d7-bd51-3124d046092a/CTPcdg_ch.pdf
[ctp-download]: https://www.simnow.com.cn/static/apiDownload.action
[ctp-auth]: https://www.nanhua.net/nanhuatech/penetrable-supervision.html
[ctp-terminal]: https://www.nanhua.net/nanhuatech/download/%E6%9C%9F%E8%B4%A7%E5%85%AC%E5%8F%B8%E5%AE%A2%E6%88%B7%E4%BA%A4%E6%98%93%E7%BB%88%E7%AB%AF%E4%BF%A1%E6%81%AF%E9%87%87%E9%9B%86%E5%8F%8A%E6%8E%A5%E5%85%A5%E8%AE%A4%E8%AF%81%E6%8A%80%E6%9C%AF%E8%A7%84%E8%8C%83.pdf
[simnow]: https://www.simnow.com.cn/product.action
[qmt-start]: https://dict.thinktrader.net/nativeApi/start_now.html
[qmt-faq]: https://dict.thinktrader.net/nativeApi/question_function.html
[qmt-trader]: https://dict.thinktrader.net/nativeApi/xttrader.html
[qmt-data]: https://dict.thinktrader.net/nativeApi/xtdata.html
[qmt-broker]: https://www.ebscn.com/software/
[qmt-inner]: https://dict.thinktrader.net/innerApi/question_answer.html
