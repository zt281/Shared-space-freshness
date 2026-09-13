# DolphinDB 社区版：因子历史与 C++ 接入事实调研

调研日期：2026-09-10。对应问题：[DolphinDB 社区版的时序存储与接入能力](../issues/17-dolphindb-community.md)。

目标：判断社区版是否具备支持跨月及更长因子时序图的基础能力，为 Tyche 后续留存、查询与部署决策提供输入。本报告不选择数据库拓扑、分区模型或升级版本，不承诺容量与性能；不改变交易毫秒关键链路。

## 结论

官方资料确认 DolphinDB 有磁盘表、历史范围 SQL、时序聚合、C++ 批量/异步写入、流订阅和备份恢复能力。因此可继续评估其作为因子历史存储候选。**免费社区版每工作节点 2 核 CPU、8GB 内存的资源限制，与所需历史长度不是同一个概念；跨月查询是否足够快仍须用实际数据量和并发负载验证。** [产品页][product]、[查询数据][queries]、[C++ 写入][write]

## 社区版资源、许可与平台

下列来源均于 2026-09-10 查阅；网页访问日期不等于条款发布日期。

| 项目 | 官方表述及计量对象 | 来源与版本边界 |
| --- | --- | --- |
| 免费版本定义 | 产品页将社区版、社区版 Pro、企业版分别列出，社区版免费；免费不等于软件本体采用开源许可。 | [产品页][product]；[软件许可及安装协议][terms]，页面未明确标注生效日期。 |
| CPU / 内存 | 社区版 **每计算或数据节点** 2 核 CPU、8GB 内存，不是整台开发机的内存，也不能理解为整个部署只能使用 8GB。 | [产品页][product]。 |
| 节点 / 部署 | 产品页写 2 个计算或存储节点，版本对比表列 **1 控制节点 + 2 个计算/数据节点**；支持单机或多机。不能把它改写成三个任意类型工作节点或三个高可用控制节点。 | [产品页][product]；具体许可证节点计数后续核对。 |
| 期限措辞冲突 | 产品页写“许可永久有效”；单节点部署教程写社区试用授权 **20 年**、单节点最大可用内存 8GB。两处措辞不一致，本报告不自行判定哪种将适用于下载包。 | [产品页][product]；[单节点部署教程][standalone]含 2.00.11.3 下载示例，未将示例版本视为当前最新版。 |
| 用途与扩展 | 产品页定位为个人/小团队开发、教学，并列支持免费插件；软件协议另规定授权范围、许可转让及二次开发等条件。资料不足以替用户确认“个人自营实盘使用及具体集成方式”已获无限制许可；也没有依据直接断言禁止该用途。 | [产品页][product]、[软件许可及安装协议][terms]。社区版 Pro 的收费、机器绑定条款不能套到免费社区版。 |
| Windows / Linux | 官方单节点教程分别说明 Windows 和 Linux 服务端；C++ API 文档列 Linux、Windows Visual Studio、Windows MinGW。 | [单节点部署][standalone]、[C++ 编译说明][cpp-platform]。具体 OS、架构、编译器与 API/Server 组合尚未锁定。 |

部署时可用 `license()` 核对 `maxMemoryPerNode`、`maxCoresPerNode`、`maxNodes`、`expiration`、`authorization`、版本和模块字段。它能检查实际资源及授权信息，但不能替代阅读许可条款；本次没有安装或获取许可证。[license 函数][license]

版本说明：能力调查使用当前在线文档；备份教程明确适用于 1.30.20/2.00.8 及之后版本。另查到 **Server 3.00.6** 兼容说明，包含部分升级后不能回退的情况，说明不能假设数据库文件与 API/Server 任意混用；本报告不宣称 3.00.6 是当前最新发行版，也未选定项目版本。[备份教程][backup]、[3.00.6 兼容说明][compat]

## 已核实能力及限制

### C++ 写入、查询与订阅

- `DBConnection` 可连接服务端、传输数据及调用脚本/函数；这是客户端访问数据库服务，不等于将数据库嵌入交易进程。[C++ API][cpp]
- C++ `MultithreadedTableWriter`（MTW）内置缓冲队列，可按行接收、分批多线程异步提交；`batchSize` 与 `throttle` 决定批量/等待条件。文档还提供按表批量追加、更新及按分区并行写入方式。旧 `BatchTableWriter` 已停止维护，不应作为新方案依据。[写入数据][write]、[MTW][mtw]
- MTW 有写入状态、成功回调、取回未发送/发送失败数据的方法；`waitForThreadCompletion()` 会等待后台工作完成。**客户端入队、服务端写入成功、进入 OS 缓存、实际刷盘是需要区分的阶段**，不能用异步入口返回值证明落盘。[MTW][mtw]、[流表持久化][persistence]
- C++ 订阅支持 `ThreadedClient` 回调和 `PollingClient` 队列轮询；官方当前文档不推荐 `ThreadPooledClient`。订阅可指定 `offset`、过滤条件及自动重订阅；offset 为行位置，不是业务时间戳，默认从当前位置开始不能直接获得跨月历史。[订阅方式][subscribe]、[ThreadedClient][threaded]

### 跨月历史与图表降采样

- 分布式表经 `loadTable` 取得对象后使用 SQL 查询；官方提供因子表按时间范围和因子名筛选的例子。分区字段过滤可剪枝，TSDB 配合 sortKey 可进一步缩小读取范围。**磁盘历史无需全部常驻内存**，但查询扫描、中间结果和返回数据仍消耗资源；官方没有为 Tyche 保证可保存几年或查询几毫秒。[查询数据][queries]
- `bar` 可将时间归入时间桶，结合聚合函数生成较低频数据；`resample` 面向具有递增时间索引的序列/矩阵，可按频度聚合。官方还有自行编写 PIP 聚合函数进行视觉降采样的教程；这不是已核实的内置 LTTB 函数，也不是对所有因子都无损的保证。[bar][bar]、[resample][resample]、[PIP 教程][pip]
- 原始因子值、时间桶的平均/极值/末值以及仅用于绘图的采样点具有不同含义。选择哪一种属于本项目后续图表语义决策，不能把显示降采样自动当成原始历史删除策略。

### 持久化与备份

- 流表默认保存在内存；需配置 `persistenceDir` 并显式开启持久化。`cacheSize` 控制内存记录规模，`retentionMinutes` 控制流日志留存；文档默认值为 1440 分钟。**流日志保留窗口不是历史磁盘表的留存政策**，不能用默认流表配置直接承诺跨月回看。[流表持久化][persistence]
- 异步持久化可能在节点崩溃/断电时丢数据；同步写入与 `flushMode` 又分别影响发布前持久化及 OS 缓冲/磁盘刷新。相应吞吐、可见性和故障丢失窗口需要一起验证。[Streaming Subscription][streaming]
- 数据库、表、分区均有备份/恢复入口，支持增量及完整性检查；教程说明备份涉及加锁、期间对应数据只读，可能影响持续写入。增量备份会覆盖相关文件，不能据此宣称可任意时间点恢复；应按需要保存不同备份代际并验证恢复。[备份恢复教程][backup]

## 对 Tyche 的工程推论（尚未决策）

1. 数据库写入与历史查询应拥有可观察的延迟、队列和错误状态。**不把每条因子的同步写库或等待刷盘插入已确认的交易毫秒关键链路**；异步隔离如何实现、是否另设落地日志仍留待架构决策。
2. 历史范围查询与实时订阅可以组成图表的数据来源，但两者切换需要定义水位、去重、排序、乱序修正与缺口显示。SDK 的自动重连不自动解决这些业务语义。
3. 跨月图表应比较服务端聚合/采样后返回与返回原始数据的成本，同时保留用户放大后查看细节的能力。显示点数预算不应与存储行数或因子计算频率混为一谈。
4. 免费版的 CPU、内存约束会同时容纳写入缓存、查询、聚合和订阅工作。把数据库与交易进程放在同机还是异机，需要实测资源争用和网络影响；本报告不选择部署方式或建议购买升级。

## 本项目后续必须验证

- **许可与版本：** 实际包的期限、节点计数、资源字段及所需功能模块；供应商对个人自营使用/集成方式的明确条件；固定 Server 与 C++ API 版本、ABI 和系统组合。
- **数据规模：** 合约数 × 因子数 × 实际写入频率 × 交易时长，以及字段宽度、版本修订、压缩比；原始与聚合历史各保留多久、磁盘和备份增长多少。所查社区版介绍未列明确磁盘容量或历史月份上限，这不等于资源无限。
- **图表指标：** 查询时间范围、曲线数量、返回点数/字节数、冷/热缓存、缩放拖动、实时写入并发下的首批结果和完成延迟；数据库耗时与网络、前端绘制耗时分开统计。
- **故障与恢复：** 写入积压上限、数据库不可用后的处理、进程崩溃/断电丢失范围、重连回放与重复记录、备份阻塞写入、完整性检查及实际恢复用时。先确定可接受数据丢失和恢复目标，再选择持久化/备份参数。

本轮仅公开资料调研；未安装服务、未取得许可、未运行写入/查询/订阅/备份样例、未做性能或容量测试。官方案例的硬件和数据集结果没有作为本项目承诺。

[product]: https://dolphindb.cn/product
[terms]: https://dolphindb.cn/product/download-term
[standalone]: https://docs.dolphindb.cn/zh/tutorials/standalone_server.html
[license]: https://docs.dolphindb.com/en/Functions/l/license.html
[cpp-platform]: https://docs.dolphindb.cn/zh/2.00.11/api/cpp.html
[cpp]: https://docs.dolphindb.cn/zh/cppdoc/cpp_api.html
[write]: https://docs.dolphindb.cn/zh/cppdoc/write_data.html
[mtw]: https://docs.dolphindb.cn/zh/cppdoc/mtw.html
[subscribe]: https://docs.dolphindb.cn/zh/cppdoc/subscribe_stream_data.html
[threaded]: https://docs.dolphindb.com/zh/api/cpp/threadedclient.html
[queries]: https://docs.dolphindb.com/zh/db_distr_comp/db_oper/queries.html
[bar]: https://docs.dolphindb.com/en/Functions/b/bar.html
[resample]: https://docs.dolphindb.com/en/Functions/r/resample.html
[pip]: https://docs.dolphindb.com/zh/tutorials/pip_ddb.html
[persistence]: https://docs.dolphindb.com/en/Functions/e/enableTablePersistence.html
[streaming]: https://docs.dolphindb.com/en/Streaming/streaming.html
[backup]: https://docs.dolphindb.com/en/Tutorials/backup_and_restore.html
[compat]: https://docs.dolphindb.cn/zh/rn/compact_report_3_00_6.html
