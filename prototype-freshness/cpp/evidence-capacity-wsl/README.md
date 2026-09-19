# 同步保存与消费者扇出：本机短时容量诊断

2026-09-19，独立原型基线 `227bbbe2969056928b348c6f60ce9188a7489730`。本轮只增加诊断入口、驱动/校验及 CMake target；Space、OrderedConsumer、DurableConsumer 和已选持久性规则没有改动。全部运行使用同一个 Release 二进制。

## 观察

14 个 case 保留初次 pilot、反向顺序重复及两种消费方式。下表的“轮”指该输入事件的所有消费者均已完成；任一消费者缺失即该轮未完成。分位数只描述已完成轮，不能掩盖未完成数，也不是尾部保证。窗口默认 2 秒、随后排空预算 3 秒；20 消费者的 ext4 低速 case 为 3 秒输入、5 秒排空预算。

| Case | 输入/s | 消费者 | 窗口内完成轮/计划 | 最终完成轮/计划 | 条件整轮 p99 ms | 窗口末积压轮 | 排空 ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| pilot-drvfs-1-50 | 50 | 1 | 100/100 | 100/100 | 11.91 | 0 | 0 |
| pilot-ext4-1-50 | 50 | 1 | 3/100 | 49/100 | 4065.75 | 97 | 未排空 |
| repeat-ext4-1-50 | 50 | 1 | 100/100 | 100/100 | 52.51 | 0 | 0 |
| repeat-drvfs-1-50 | 50 | 1 | 100/100 | 100/100 | 8.09 | 0 | 0 |
| drvfs-durable-1-200 | 200 | 1 | 320/400 | 400/400 | 469.53 | 80 | 466.55 |
| drvfs-durable-4-20 | 20 | 4 | 40/40 | 40/40 | 20.07 | 0 | 0 |
| drvfs-durable-4-100 | 100 | 4 | 120/200 | 200/200 | 1313.78 | 80 | 1298.61 |
| drvfs-durable-20-5 | 5 | 20 | 10/10 | 10/10 | 93.67 | 0 | 0 |
| ext4-durable-1-5 | 5 | 1 | 10/10 | 10/10 | 20.30 | 0 | 0 |
| ext4-durable-4-5 | 5 | 4 | 10/10 | 10/10 | 33.97 | 0 | 0 |
| ext4-durable-4-20 | 20 | 4 | 40/40 | 40/40 | 32.88 | 0 | 0 |
| ext4-durable-20-1 | 1 | 20 | 3/3 | 3/3 | 37.78 | 0 | 0 |
| drvfs-ordered-1-50 | 50 | 1 | 100/100 | 100/100 | 2.50 | 0 | 0 |
| ext4-ordered-1-50 | 50 | 1 | 100/100 | 100/100 | 7.91 | 0 | 0 |

- pilot/repeat 和 `durable` 保留逐事件检查点；`ordered` 不保存消费状态，只用于诊断成本，不是已选恢复方案。
- 初次 ext4 50/s 仅 49/100 轮在退出前完成，反向顺序复测却全部完成；初次与复测均保留，不挑较好结果。短样本不足以解释波动原因或给出稳定容量上限。
- D 路径 1 消费者 200/s、4 消费者 100/s 均出现明显窗口积压；20 消费者低速能完成的样本仅为 10 轮和 3 轮，不代表长期或高负载容量。
- 本轮所有进程正常退出、没有字段/顺序错误；这表示测量数据通过核对，**不表示性能达标**。初次 ext4 的未完成需求是明确记录的诊断结果。
- 发布调用的延迟包含共享锁等待和同步保存；消费者调用包含共享空间访问、同步检查点及内部后续状态检查。没有观测到的内部阶段不被单独归因。来源 head/publish 与 checkpoint 内部完成时刻未公开，使用公开调用返回上界。
- Record 的逻辑 tick 在实际发布调用时生成，测量延迟则由事先计划的到达时间开始。本轮不证明真实市场数据年龄或交易就绪条件。

## 环境与测量边界

Windows Ryzen 7 3700X（8 物理核、16 线程），约 48 GiB RAM。实际 WSL 配置只有 8 vCPU 和 8GB 上限，Ubuntu 24.04.4 / Linux 6.18.33.2；未改电源、CPU 频率、资源限制或绑核。详见 `environment-windows.json`、`environment-linux.json` 和每个 manifest 中的 affinity/挂载信息。

- D 路径：`/mnt/d` 的 DrvFs/9p → NTFS，底层 Great Wall GW600 4TB SATA SSD。
- ext4 路径：Ubuntu VHD 位于 C 盘，底层 KINGSTON SA400S37240G SATA SSD。**同时改变了物理 SSD 和存储栈，不能作文件系统单因素对照。** 测完后原始 ext4 case 完整复制到本目录，manifest 仍保留实际运行路径；原件没有删除。
- 编译目录位于 `/home/alan/.cache/tyche-prototypes/capacity-20260919`。各 case 的业务日志/checkpoint 位于其实际运行目录，并非所有结果都在构建目录所属 ext4 上测得。
- 事先固定到达率/事件数，源变慢不顺延后续计划。自主 C++ 循环通过具名 Space 传递事件，控制管道只有开始/结束保存屏障。无事件时消费者按固定 100 微秒轮询等待。
- 初始化事件、进程启动及初始检查点被排除。没有恢复重放、真实拟合/报价/发单、生产完整指标持久化热路径或跨机通信。
- 逐事件时序存入预分配内存，全部进程停止计时后才统一保存 CSV；业务日志/checkpoint 仍按原实现同步。进程崩溃可能丢失本轮诊断，不能把这些测量数组当作可恢复业务证据。
- 期限在 API 调用之间检查，无法打断已开始的内核 I/O；原始资源记录及派生 `max_deadline_overrun_ms` 保留超期完成，本轮最大超出 25.76ms。CPU/RSS 是 `getrusage` 观察，RSS 为含启动的生命周期高水位。
- 单机单调时钟不可跨主机比较。小样本经验 p99 不提供 p99/p99.9 保证；不能据本轮宣布稳定容量、完整策略容量、网络能力或生产低延迟达标。

## 原始证据与派生分析

每个 case 保留完整计划/完成 CSV（未完成行仍在）、原始业务日志、durable 检查点、资源 JSON、进程命令/退出/屏障、manifest、运行时源码快照、Release 编译参数和 SHA-256。原始 `hashes.json` 和 `summary.json` 没有重写。

初次两个 pilot 的驱动尚未生成整轮与 100ms 曲线。现在以 `analysis/sources/` 中明确捕获的后处理脚本统一重算全部 14 个 case，结果另存在 `analysis/<case>/`，包括 `summary.json`、`rounds.csv`、`backlog-100ms.json`。各组、混池、整轮及最慢组分别记录；`summary-table.json` 仅为便览。

`audit.json` 记录后处理命令、UTC、脚本哈希、每个原始 manifest/summary 的输入哈希及原始/派生文件哈希，明确区分测量源码与后处理源码。目录级 `.gitattributes` 禁止换行转换，保持保存的字节。

复现采样和全部边界见 [CAPACITY.md](../CAPACITY.md)。离线复核：

```bash
python3 prototype-freshness/cpp/capacity_audit.py prototype-freshness/cpp/evidence-capacity-wsl
```

## 捕获标识

- Release 二进制 SHA-256：`0c2fdc32a20385741d56816ce8315f6b12f40b64510564d155859f0f1e756e76`。
- 最终 `capacity_probe.cpp` SHA-256：`1181b1b8a2906315c57ae51e737a1ea6ce0d05fbb9067842f2b8634e3e8c4cf2`。
- 最终 `capacity_run.py` SHA-256：`12a8649bb8dc9e078606ebb194ab1b372cc4a721e427dd649295e6357da32efd`。
- 最终 `capacity_audit.py` SHA-256：`3383381705afe0e8d9bda94fb64c3b2e39b796fe752a91c0eb7c57a0fc05cbc9`。
- 原始计划 1,313 轮、2,430 次消费；实际完成 1,262 轮、2,379 次消费。缺失的 51 次/轮均来自初次 ext4 pilot，不被从分母移除。
- 14 个 case 全部核对原始哈希、二进制事件、逐事件载荷/顺序与检查点结果；所有 worker exit_code=0，stats.error 为空，payload/sequence 错误计数为 0。
