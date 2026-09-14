# 跨网络共享虚拟内存的实现语义与故障边界

Type: research
Labels: wayfinder:research
Status: resolved
Assignee: shared_memory_research
Parent: ../map.md
Blocked by: none

## Question

用户提出 Tyche 的核心目标：插件式系统，国内/境外及本地节点共享连续虚拟内存，行情和指令通过该空间实现零拷贝高速通信；跨市场和本地策略采用相同拓扑；节点重连同步后自动启动，非关键模块失联仅限制功能，持仓/风控等关键模块失联要求后台急停。

通过有界第一方资料研究区分：同机共享内存、相同虚拟地址映射、分布式共享内存及缓存一致性、RDMA/one-sided access、普通网络复制和零拷贝的准确范围。核实 Ubuntu/Windows、本地/普通国内境外服务器条件下的硬件与网络要求、延迟和故障发现限制；不把去除 CPU 拷贝等同消除网络传输或跨节点强一致代价。

提出少量满足统一插件接口目标的候选及其取舍，明确直接指针访问与句柄/偏移量、显式发布和同步、一写多读与多写、网络分区、陈旧读、重启代次/索引相同却内容不同、重复指令及失效节点恢复的差异。以用户决定为边界，不擅自改成普通 RPC 架构或宣布目标不可行，不替用户选择一致性模型。

报告保存 ../research/network-shared-memory.md，研究分支 research/network-shared-memory。仅研究，不构建实现，不做网络/性能承诺。

## Resolution comment — 2026-09-14

完成有界第一方研究，区分同机映射、透明 DSM、RDMA 和普通网络共享区域复制；固定虚拟地址不产生跨机器一致性，RDMA 不等于透明指针或一致性协议，零拷贝须按路径验证。已提供三种保持统一插件拓扑的候选，未选定传输或一致性算法。研究期间用户确认统一空间接口、完整版本显式发布、按关键模块依赖路径急停；具体决议由父票记录。

恢复不能只比较索引，需代次/完整版本/权威状态及外部订单核对；故障检测非瞬时，失效代次必须在执行端强制检查。

研究资产：[跨网络共享虚拟内存的实现语义与故障边界](../research/network-shared-memory.md)。研究分支 `research/network-shared-memory`，独立工作区 `/tmp/tyche-shared-memory-research`。无实现、无性能实测；研究关闭不表示架构选择完成。
