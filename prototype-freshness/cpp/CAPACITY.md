# 共享空间同步保存与消费扇出短时诊断

这是一次性诊断，不是生产容量基准。问题是：保留现有日志同步和逐事件检查点时，当前 Windows/WSL 主机在两条实际存储路径上有哪些可观察成本、积压和波动？不模拟 500 资产、不运行拟合算法、不连接交易或网络行情。

## 运行与复核

从独立原型仓库根目录，在已有 Ubuntu WSL 中运行；每次 `--root` 必须是不存在的新目录：

```bash
cmake -S prototype-freshness/cpp -B /home/alan/.cache/tyche-prototypes/capacity-20260919 -DCMAKE_BUILD_TYPE=Release
cmake --build /home/alan/.cache/tyche-prototypes/capacity-20260919 --target capacity_probe --parallel 4
python3 prototype-freshness/cpp/capacity_run.py \
  --binary /home/alan/.cache/tyche-prototypes/capacity-20260919/capacity_probe \
  --root /mnt/d/dev/Tyche-freshness-prototype/prototype-freshness/cpp/my-new-capacity-run \
  --rate 50 --seconds 2 --drain 3 --fanout 1 --mode durable
```

`--fanout` 支持 1、4、20；`--mode ordered` 只作未保存消费状态的诊断对照，不是已选恢复方案。将新运行目录改到 `/home/alan/...` 可测另一条实际路径；这会同时改变文件系统、WSL 存储栈和底层 SSD，不是单因素文件系统实验。不要复用旧目录或删除已有证据。

已保存的 14 次运行与结果见 [证据说明](evidence-capacity-wsl/README.md)。仅离线重算及校验：

```bash
python3 prototype-freshness/cpp/capacity_audit.py prototype-freshness/cpp/evidence-capacity-wsl
```

该命令核对原始哈希、事件二进制、逐笔 CSV、checkpoint 和进程退出；只在 `analysis/` 重新生成统一口径派生结果，并更新汇总/audit。各运行原始 `summary.json`、源码快照与 `hashes.json` 保持不变。也可用 Windows Python 执行离线校验。

## 测量口径

- C++ 发布者和消费者均全新 exec 并独立挂接具名共享空间。Python 管道只负责开始、完成后统一保存两道屏障，不逐事件调度。
- 输入在开始前已固定总数和逐条到达时刻。源慢时保留未开始的需求，后续计划不会顺延；窗口结束后仅允许有界排空。期限在操作之间检查，不能中断内核文件 I/O，原始时间会保留任何超期完成。
- 发布/消费循环自主运行；消费者无事件时等待 100 微秒。此策略始终不变，也不代表最终通知机制。
- 底层 `Space`、`OrderedConsumer`、`DurableConsumer` 未改动。日志仍持锁逐条 `fdatasync`，durable 检查点仍逐事件文件同步、名称替换和目录同步。
- 一个初始化事件及进程启动/初始检查点不计入输入。未进行恢复重放计时；各 case 均创建新日志。每条业务记录为同一种 96 字节合成载荷；检查点为 128 字节纯累计结果。
- `CLOCK_MONOTONIC` 纳秒只比较同机进程。延迟从**预定到达时刻**开始，记录实际开始、prepare 返回、publish 调用及返回、consume 开始及返回。Record 的逻辑 tick 在实际发布时生成，因此本诊断不证明真实源数据年龄或交易就绪门槛。
- DurableConsumer 未暴露内部同步完成时点；consume 返回仅作为处理及检查点已完成的时间上界，不把两者虚构成可独立测得的内部阶段。publish 返回也可能晚于其他消费者实际观察到发布。
- 所有计划事件都有 CSV 行；未完成不从分母消失。单组、混池和“该事件所有消费者最后完成”的整轮结果分别保留；缺少任一消费者即整轮未完成。分位数是**已完成样本的条件经验统计**，不保证 p99/p99.9。
- 100ms 积压曲线由完整计划与完成时间离线重建。窗口积压包括未开始/未发布的需求；另列基于 publish 返回上界的已发布积压，避免用最新快照掩盖遗漏。
- 时间行在测量前预分配内存。所有进程停止计时后才统一写 CSV；诊断不包含生产完整指标持久化的热路径成本，进程崩溃时可能丢失本轮诊断。业务日志/checkpoint 的同步语义没有减弱。
- CPU 时间取开始屏障前后进程 `getrusage` 差值；RSS 是进程生命周期高水位，包含启动。未改 CPU 频率、电源、WSL 限额或绑核；只记录实际 affinity。

## 结论边界

低速短窗口完成不等于可持续容量；积压和一次排空失败是本轮真实观察，也不等于稳定生产上限。初次 ext4 50/s 严重积压在反向复测中未重现，两次都完整保留。两路径位于不同 SATA SSD，不能将差异归因于文件系统。

这里没有真实资产扇出、定价/曲面拟合、订单处理、生产指标开销、长时间压力、Windows 原生或跨节点验证。不能把正确性审计通过写成性能达标。
