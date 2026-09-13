# Electron/Vue 多窗口交易台：技术边界调研

调研日期：2026-09-10。范围：6 个 Electron/Vue 官方文档页面；Electron 使用 `/docs/latest/` 文档，尚未锁定项目版本。本报告提供事实与决策依据，不代表架构定案或性能测量结果。

已知需求：Windows、Electron + TypeScript + Vue、多屏独立窗口、大量盘口与策略；C++ 后台独立运行，前端退出后继续运行；数百合约、十几个以上策略，后台要求毫秒级反应。以下“推论”是结合这些需求的工程判断。

## 已核实的技术事实

### 1. main、preload 与 renderer

Electron 应用有一个 main 进程，具备 Node.js API，负责窗口和应用生命周期；每个 `BrowserWindow` 对应独立 renderer，窗口销毁时对应 renderer 终止。preload 在 renderer 内执行，但默认 `contextIsolation` 将其与页面 JavaScript 环境隔离；renderer 默认不能直接访问 Node.js。通过 `contextBridge` 提供所需能力。[Electron Process Model](https://www.electronjs.org/docs/latest/tutorial/process-model)

**推论：** 多窗口复用同一 Vue 代码不等于共享一份内存状态。交易状态来源、窗口订阅和窗口间布局状态需要明确的所有权与同步规则；窗口缓存不能成为后台继续运行所依赖的状态。

### 2. IPC 与 contextBridge

renderer→main 的单向消息使用 `send/on`，请求响应使用 `invoke/handle`；main→renderer 可使用 `webContents.send`。官方要求通过 preload 暴露有限的方法，避免暴露整个 `ipcRenderer.send`。IPC 使用结构化克隆，只能传递支持序列化的值，不能把 DOM 或部分 Node/Electron 原生对象直接作为消息。[Electron IPC](https://www.electronjs.org/docs/latest/tutorial/ipc)

**推论：** 应定义可序列化的命令、回执和状态数据，而非跨窗口共享对象引用。TypeScript 类型不能代替运行时消息校验。订单受理回执与最终交易所状态应在业务协议中区分；IPC 调用返回本身不表示订单成交。

### 3. MessagePort 与窗口间通信

main 使用 `MessagePortMain/MessageChannelMain`，renderer 使用 Web `MessagePort/MessageChannel`。端口通过 `postMessage` 转移，普通 `send/invoke` 不能转移端口。main 可先分发端口，使两个 renderer 后续直接通信；端口也可传给 Web Worker。官方同时展示保留 context isolation 的端口交接方法，简化示例中的关闭隔离配置不应被当作必要条件。[Electron MessagePorts](https://www.electronjs.org/docs/latest/tutorial/message-ports)

**推论：** MessagePort 是内部数据分发的候选方案，不自动提供业务状态同步、持久化或背压规则，也不能据此承诺吞吐量。是否减少 main 转发，应以真实负载比较决定。

### 4. Worker 的可用范围

Web Worker 可在操作系统线程执行 JavaScript。若启用 `nodeIntegrationInWorker`，必须不启用 sandbox；该 Node 集成不适用于 SharedWorker/Service Worker。Electron 内置模块不能用于多线程环境。官方另指出原生 Node 模块的线程及加载安全限制。[Electron Multithreading](https://www.electronjs.org/docs/latest/tutorial/multithreading)

**推论：** 可以评估让普通 Web Worker 处理前端解析、聚合等计算；不能把它当作 Electron 窗口 API 的并行执行入口。需要 Node 能力的任务必须另评估进程放置，不能为了并行计算顺手取消隔离。

### 5. utilityProcess 与独立 C++ 服务

`utilityProcess.fork(modulePath, ...)` 只能在 main 且 app ready 后调用，入口是脚本，创建带 Node.js 与消息端口能力的子进程；它可与 main 交换消息和转移端口。[Electron utilityProcess](https://www.electronjs.org/docs/latest/api/utility-process)

**推论：** 该 API 不是直接运行任意 C++ `.exe` 的接口，也不等于独立后台服务部署。Electron 内部 IPC/MessagePort 的文档不提供独立 C++ 服务器协议；需要另行设计网络或操作系统通信接口。main 的 Node 能力允许实现客户端适配，但“main 中连接”与“独立前端辅助进程中连接”仍待选择。前端退出后继续交易的保证必须来自 C++ 服务的独立生命周期，并通过故障实验验证，不能从子进程 API 名称推导。[Process Model](https://www.electronjs.org/docs/latest/tutorial/process-model) · [utilityProcess](https://www.electronjs.org/docs/latest/api/utility-process)

### 6. Vue 大列表与高频状态

Vue 官方建议大列表只渲染视口附近元素，保持子组件 props 稳定，并避免大量无必要组件层级。默认响应式是深层的；`shallowRef/shallowReactive` 可减少大结构的追踪开销，代价是嵌套内容按不可变数据处理，通过替换根状态触发更新。官方提供 Chrome DevTools、Vue 性能标记和 Vue DevTools 等测量途径。[Vue Performance](https://vuejs.org/guide/best-practices/performance.html)

**推论：** 数百合约不应简单变成每个行情事件都重绘所有窗口。可比较按窗口订阅、按显示节奏合并行情、分块替换浅状态等方案；合并策略必须区分行情展示与订单/成交事件。浅响应式本身不解决大对象复制和频繁分配成本。

## 对架构讨论的直接启示

以下是候选原则，尚未选择最终实现：

- 把前端当作能断开、重连并重建显示状态的客户端；业务执行不能依赖 renderer 的存活。
- 把窗口管理、受限桌面 API、后台连接、数据分发和 Vue 展示视为不同职责；是否分别放进独立进程由负载及故障隔离需求决定。
- 将 Electron 内部通信与 C++ 服务协议分别定义。跨窗口订阅和协议重连应有明确状态恢复语义。
- 将后台决策延迟、客户端收到状态的延迟、画面呈现延迟分别计量；官方文档没有为本项目负载提供毫秒级或帧率保证。

## 尚需决策的问题

1. 独立 C++ 服务只支持本机，还是也支持远程部署？这决定传输、身份认证、版本协商与连接恢复的约束。
2. 后台连接由一个前端适配层复用，还是各窗口建立连接？窗口间哪些状态共享，哪些只保存到工作区布局？
3. 各类数据的权威来源、快照/增量切换、序号缺口处理和重连恢复规则是什么？哪些中间状态允许合并展示？
4. 最大窗口数、同时可见盘口数、盘口深度、推送峰值与目标显示刷新频率分别是多少？
5. “毫秒级反应”的测量起止点、分位数、允许峰值、指定硬件及过载条件是什么？

## 测试时必须验证的指标

这些是待建立的验收口径，不是已经测得的结果。

| 维度 | 需要记录与比较 |
|---|---|
| 后台独立性 | 关闭所有窗口、退出 Electron、杀死 renderer/main 后，后台 PID、策略事件处理与订单状态推进是否继续；重新打开前端后的状态收敛时间 |
| 后台延迟 | 明确从行情进入到策略输出/订单发送的边界，统计 p50/p95/p99/p99.9；比较无前端、满窗口和前端卡死时的变化 |
| 通信与背压 | 各段消息/字节吞吐、序列化耗时、队列深度及最老消息年龄；记录合并、丢弃、重传和序号缺口数量 |
| 显示与交互 | 收到行情到绘制的延迟、帧时间分布、输入响应、长任务、GC 暂停；覆盖滚动、拖动窗口和切换合约 |
| 资源与恢复 | 每进程 CPU/RSS、GPU 占用、窗口增加的资源增量、长时间运行内存趋势；连接断开、窗口重建、突发行情后的恢复时间 |

负载矩阵应包含目标 Windows 硬件、显示器数量/刷新率/DPI、数百合约及策略数量、可见/隐藏/最小化窗口、稳定流量与突发流量；固定 Electron/Vue 版本和生产构建后比较方案。此轮没有安装依赖、编写原型、访问账户或执行基准测试。
