# Tyche 多资产交易系统架构决策地图

Labels: wayfinder:map

## Destination

形成可指导后续实现的多资产交易程序架构设计：明确模块职责、进程与部署关系、接口边界、关键数据流及分阶段实施路线。终点是主要架构问题已有明确答案；本轮不生成可运行的程序骨架。

## Notes

- 已确认技术栈：C++ 后端；Electron + TypeScript + Vue 前端，兼顾外观和性能。
- 已确认使用方式：个人、多交易账户，手工交易与自动策略并存。
- 用户指定首批接入：Binance、CTP 中国期货期权、QMT 股票市场；股票借券卖空另选支持该能力的通道。各接入的具体产品和能力范围以相关决议为准。
- 每次继续本地图使用 wayfinder、grill-with-docs（含 grilling 和 domain-modeling）。设计模块时参考 codebase-design；研究问题使用 research；交易数据路径参考 engineer-hft-cpp-platform。
- 先查官方事实，再询问产品取舍；调研不代表用户已经选择某项架构。暂不以使用 C++ 为由假定微秒级延迟指标。
- [业务术语](../../CONTEXT.md)仅记录术语。重要且难以逆转的取舍确定后，再按需创建 `docs/adr/`。
- 第二轮输入已追加至相关问题单的 Comments：它们约束后续设计，不表示完整架构问题已解决。
- 性能原型属于用户已选择的决策验证方式，使用独立目录和分支保留；实际容量以原型结果及其覆盖范围为准。
- 工作台支持按功能分类创建多个面板实例，用户自行组织布局；多窗口原型验证显示与操作目标，不把讨论用的面板数量固化为功能上限。
- 追踪格式与当前可处理问题的查询方式见 [本地追踪约定](README.md)。

## Decisions so far

- [Binance 产品与官方接入能力](issues/02-binance-products.md)：股票形态、API 家族、账户能力与资金语义需要分别表达。
- [CTP 与 QMT 的接入和运行约束](issues/03-ctp-qmt-access.md)：CTP 可原生 C++；QMT 的公开 Python 路径与客户端依赖需要单独决策。
- [Electron 多窗口的数据与权限边界](issues/11-electron-boundaries.md)：内部 IPC 与独立后台协议分开设计，多窗口显示能力按负载验证。
- [策略运行方式与性能预算](issues/04-strategy-performance.md)：C++ 策略按组隔离，逐笔拟合与每组 100 期权双边报价纳入整轮延迟目标，吞吐经原型定档。
- [DolphinDB 社区版的时序存储与接入能力](issues/17-dolphindb-community.md)：具有 C++ 接入和历史查询基础能力，社区版资源与持久化边界需纳入后续容量及存储决策。
- [交易工作台的信息布局与刷新目标](issues/05-workbench-workflow.md)：分类创建面板与多屏工作区、参数编辑和价格梯交互已明确，分级刷新与反馈延迟由原型验证。
- [Binance 股票产品的程序化交易与做市边界](issues/21-binance-stocks-market-making.md)：已核实股票接口与实时流，但当前证据不能满足两类股票的借券卖空要求。
- [Binance BTC 与 ETH 衍生品的做市及账户能力](issues/22-binance-crypto-market-making.md)：合格用户可卖出开仓，普通保证金、做市商保护权限和实际账户验证分别处理。
- [Binance 首版产品与交易权限范围](issues/12-binance-scope.md)：普通账户接 BTC/ETH 期权和 USDT 永续，均需双边做市；股票保留借券要求并另选通道。

## Not yet specified

- 首批通道验证之后的扩展方式，待其共性和差异被实际资料揭示后继续梳理。

## Out of scope

- 本轮的应用代码、可运行骨架和正式部署：用户已选择先完成架构设计与决策地图。
- 本轮的账户开通、凭据配置与真实交易操作：不属于架构设计产出。
- Binance Direct Stocks 与 bStocks 的首版接入暂缓：当前借券卖空能力与业务要求不匹配，股票通过另选通道承接，见 [Binance 首版范围决议](issues/12-binance-scope.md)。
- 组合保证金实际交易路径，以及自动钱包划转、币种兑换和股票代币转换，留到首版之后；本轮仅明确必要的识别与扩展边界。
