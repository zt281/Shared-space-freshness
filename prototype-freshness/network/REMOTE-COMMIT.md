# QUIC 远端有界保存对照

本轮回答：把远端核验后的保存从唯一应用工作线程移到每条日志一个有界保存队列后，能否在保留连续序号核验、先保存后发布和失败限制的条件下释放接收反压？这是当前 Windows/WSL 的有限原型实验，不是正式存储、网络或策略容量验收。

## 三个模式与共同边界

| 模式 | 远端执行方式 | 同步与发布 |
| --- | --- | --- |
| `sync` | 原应用线程逐条 `ReplicaSpace::accept`（现状，对照基线） | 每条 pwrite + fdatasync，共享锁内逐条 install |
| `worker` | 每条日志一个 `RemoteBatchSaver` 写线程 | 逐条写盘与同步；磁盘等待移出应用线程 |
| `batch` | 与 `worker` 相同的两个写线程 | 最多 8 条、候选合批窗口 2ms，整批一次 fdatasync 后在一次共享锁内发布 |

两个异步模式各日志最多 64 条待保存记录，包含排队和正在保存的记录。应用线程仍独占 received/durable/visible 水位、缺口检测、进度回复和订阅重协商；写线程只做 pwrite + fdatasync + 既定共享锁临界区 install，完成经应用任务队列回报。先保存后发布不变：整批一次同步完成后才在共享锁内发布该批，`D/V` 在发布完成后一起推进，`A ≤ V ≤ D ≤ R ≤ C` 不变。两个消费者仍逐事件保存结果/进度检查点，消费触发间隔约 20ms，本轮完全未改。

64 条上限只限定尚未保存完成的输入；进程总内存还包括接收借用、传输缓冲、日志读缓存及诊断旁路，完整字节预算不能仅由待保存条数推出。2ms 是合批收集窗口，不限制前序排队和调度等待。每日志一线程仅用于两个对象的对照，不能外推成更多对象各建一条写线程。`sync` 与 `worker` 的差别同时包括线程布局和磁盘等待位置；`worker` 与 `batch` 使用同一代码路径，仅改变每批上限和等待。

远端接纳时核验连续序号与内容指纹，接纳不代表保存成功。队满是暂时跟不上而不是保存失败：限制受影响对象（不置 damaged）并关闭包含它们的复制连接；已接纳前缀继续排空，源端重连后按既有缺口从最后确认保存的游标补读恢复。当前两个对象可能共享一条连接，一个对象队满牵连同连接另一对象是既有已知限制，本轮保留。远端保存失败维持现有的永久受限（damaged/blocked、拒绝接管）语义，不新增自动修复、截断或重试覆盖。共享内存、磁盘格式和 QUIC 帧格式未改变；新增接口只是实验命令与诊断旁路。

合批时每事件仍各打诊断标记（`replica_write_begin/written`、`replica_sync_begin/end`、`replica_publish_enter/locked/published`，同步与发布标记带批次大小），整批共享同一次真实 fdatasync 区间；实际同步次数取保存器计数，不能数逐事件诊断标记充当系统调用次数。

环境开关（合成实验配置，未选为生产参数）：`TYCHE_QUIC_REMOTE_MODE=sync|worker|batch`（默认 `sync`）、`TYCHE_QUIC_REMOTE_CAPACITY`（每日志 1..64）、`TYCHE_QUIC_REMOTE_WAIT_NS`（batch 默认 2,000,000，其余模式必须为 0）。新增远端故障命令：`remote_gate`/`remote_release`（一次性出队前门闩，管道信号）、`remote_arm <流> <0..6>`（批级崩溃点）、`remote_sync_error <流>`（下一次批同步失败）；原有 `gate_sync`/`arm`/`sync_error` 仅限 `sync` 模式，行为不变。`close()` 在连接与应用任务排空后继续把已接纳记录全部写盘同步再退出；`status` 增加 `remote_mode`、`overflows` 与每日志 `savers` 指标。

## 故障与证据要求

新增第八组 CTest `quic_remote_commit_scenarios`，13 个场景 169 项检查：`worker`/`batch` 各覆盖有序交付（门闩下确定接纳 24 条后放行，验证单写线程 25 次同步与合批 4 次同步的区别计数、注入重复不二次保存、字节级源=副本、消费者检查点重启）与保存门闩（门闩下 R 推进、D=V 不动、副本日志零增长、消费者读不到）；容量 4 队满（受限+断连+排空+重连补读到 7 条，无 storage_failed）；远端保存错误（620 字节未确认整批尾保留、D/V 不推进、替代进程退出码 1 拒绝接管、字节不变）；批级崩溃点 0..6（门闩造出确定的 4 条批后放行崩溃：崩溃时日志分别保留 124/248/310/620/620/620/620 字节；点 2 半条尾拒绝接管且不截断；其余在确认旧实例退出后恢复精确持久前缀、补读至 5 条、消费者恰好一次处理；点 6 已发布未回报）。

独立审计重新解码 96 字节源记录、124 字节大端副本和 128 字节检查点，逐条核对序号、载荷、seal 与先后关系；只有旧实例已退出才启动替代实例。私有临时测试密钥不进入证据树。

## 负载方法

同一 Release 二进制、直接本机 QUIC、运行时日志位于 WSL ext4；源端固定 `sync` 默认模式作为本轮固定条件，只切换远端模式。每档交替输入两条对象日志，共 80 条，另各有一条初始化记录：平稳档 40 条/秒、2 秒；突发档平均 80 条/秒、1 秒，每 100ms 同时计划 8 条。迟到不后移计划，不等前一提交答复才安排下一条。最多再排空 12 秒，所有计划、拒绝、未完成和进度均保留。三轮按 `sync/worker/batch`、`worker/batch/sync`、`batch/sync/worker` 轮换顺序；各模式开启相同有界诊断旁路。

基准期间不并行本任务的构建、审计或其他实验；宿主及其他应用没有隔离。有限样本、顺序对照和 Windows/WSL 存储波动不能证明固定性能收益或生产尾分位数。仅 80 条时最近秩 p99 就是最大值。保留的旧 D/DrvFs 检查点替换 `EACCES` 未解决，ext4 条件不构成对其修复。

## 复现

在既有私有 MsQuic v2.6.1 / QuicTLS 环境中依次运行，每条必须等进程退出后再运行下一条：

```sh
python3 stage_validate.py release --series remote-commit
python3 stage_validate.py ubsan --series remote-commit
python3 remote_commit_probe.py --worker /home/alan/.cache/tyche-prototypes/quic-20260919/remote-commit-release/quic_worker \
  --evidence-root /home/alan/.cache/tyche-prototypes/quic-20260919/remote-commit-network --smoke
python3 stage_audit.py /absolute/path/to/smoke-evidence
python3 remote_commit_probe.py --worker /home/alan/.cache/tyche-prototypes/quic-20260919/remote-commit-release/quic_worker \
  --evidence-root /home/alan/.cache/tyche-prototypes/quic-20260919/remote-commit-network
python3 stage_audit.py /absolute/path/to/matrix-evidence
python3 remote_commit_audit.py /absolute/path/to/remote-commit-fault-evidence
python3 remote_commit_verify.py   # 归档后在仓库证据树上总复核
```

私有临时测试密钥不进入证据树。没有真实行情、订单提交、外部资源购买或部署。

## 最终结果

最终 Release 与 UBSan 各 **8/8 CTest、959 项检查通过**：原本地 499、QUIC 复制 124、源端 14 场景 167、新远端 13 场景 169。构建、源码和原始测试分别保存在 [Release](evidence/remote-commit-release-f9169e17e608/manifest.json) 与 [UBSan](evidence/remote-commit-ubsan-bad96d41a4fb/manifest.json)。最终 worker SHA256：

- Release：`fffe5106df8d2ec0ea4a8197030b6b4c53c9d84ef15e238a14a6bcb7bf73ab23`。
- UBSan：`8ddfa391ed5dfe0e7e18dbf89fe95c0e108f622793f58ad011548bc39edcf3d4`。

依赖仍为固定 MsQuic v2.6.1；库 SHA256 `10d88b8fcdc411952430525bdc08885ca3b09899e371f2924f7c6c41bc516b7a`。UBSan 检查自己的 C++，依赖仍为 Release 构建。两份最终源码快照与本轮代码一致。故障证据经[独立审计](evidence/remote-commit-release-f9169e17e608/runs/)逐字节复核（Release 与 UBSan 各 13 场景 169 项）。

[最终 18 档测量](evidence/remote-commit-matrix-07ed7631b01c/manifest.json)的 **1,440/1,440 条全部完成**，每条均有完整阶段；[独立审计](evidence/remote-commit-matrix-07ed7631b01c/stage-audit.json)核对源、远端队列段、检查点及唯一标记不变量。无拒绝、未知结果、旁路溢出或过期观察。初始化记录不计入下表的 80 条。

| 突发轮次 | 模式 | 输入窗口内完成 / 80 | 计划至内部完成中位数 ms | 最大值 ms | 远端同步次数 | 源端同步次数 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | sync | 59 | 221.84 | 333.80 | 82 | 80 |
| 1 | worker | 59 | 200.25 | 309.66 | 82 | 80 |
| 1 | batch | 63 | 166.66 | 233.47 | 82 | 80 |
| 2 | worker | 64 | 246.05 | 306.30 | 82 | 80 |
| 2 | batch | 65 | 166.74 | 284.28 | 82 | 80 |
| 2 | sync | 61 | 169.49 | 251.57 | 82 | 80 |
| 3 | batch | 61 | 182.85 | 266.97 | 82 | 80 |
| 3 | sync | 58 | 230.10 | 340.99 | 82 | 80 |
| 3 | worker | 60 | 198.68 | 305.38 | 82 | 80 |

**远端合批在本矩阵无批可合**：固定条件的同步源端每条一次 fdatasync（约 7–12ms）把到达隔开，全部 18 档远端保存队列 `max_pending` 均为 1，三模式远端同步次数同为 82（80 条 + 2 条初始化）；batch 的 `remote_save_queue` 中位约 2.04–2.11ms 是纯窗口等待。本轮只验证了合批机制的正确性（故障场景以门闩造出确定批次），**没有测出远端合批的负载收益**。

worker 的真实机制效果在接收端可见：两日志不再在唯一应用线程上串行等待磁盘，`R→remote_written` 最大值从 sync 平稳档的 **28.11ms** 降到 worker/batch 的 **≤3.84ms**；突发档中位 `R→remote_written` 从约 0.99ms 降到约 0.06ms。突发尾部仍在别处：`V→consumer_begin` 中位 84.75–120.56ms（消费者约 20ms 轮询加逐事件检查点，本轮固定未改）。最慢事件为 sync 突发第三轮 index 79 的 **340.99ms**：源端应用排队 117.11ms（同步源串行保存所致）、远端发布至消费开始 173.38ms、检查点文件与目录同步 11.37/7.41ms；完整逐事件分解在审计文件，不能相加不同阶段的分位数。

平稳输入下三模式 78–79/80 在窗口内完成，内部完成中位数 sync 46.44–49.82ms、worker 40.88–46.36ms、batch 46.54–49.00ms；sync 第一轮最大值 262.28ms 高于异步两档（59.58/67.61ms）。样本有限且宿主未隔离，不能据此宣称固定收益或尾分位结论。

最终样本接收进程观测到 sync 12 个线程、两个异步模式各 14 个线程（+2 保存线程），RSS 约 15 MiB 量级（第一轮平稳档 15,008 / 15,072 / 15,028 KiB，含诊断缓冲）。CPU tick 与上下文切换只是有限采样跨度内的诊断，不是满载容量。

## 保留的波动及下一步

各次单调时钟只在本次运行内关联，不跨运行拼接；当前宿主/WSL 存储与调度波动尚未隔离。异步远端下“同序异内容”走接纳比对路径（队列/在写/日志三层），仅有同步路径的既有冲突场景覆盖，异步冲突没有专门场景；队列窗口内重复比对只在溢出重连竞态中出现，本轮无确定性场景（注入重复覆盖的是已确认前缀比对路径）。两对象共享连接的队满牵连保留。

远端候选已具备机制证据，可以进入后续架构比较；64 条、8 条、2ms 和每对象一线程尚未选为生产参数。下一轮优先把源端异步与远端异步组合，让突发真正越过网络抵达远端队列，再评估合批收益；消费者逐事件检查点继续作为固定条件。若需要改变消费者提交/恢复边界，再通过 grill-with-docs 明确取舍。

本轮没有真实拟合、报价、风控、交易接口或生产指标保存负担；不是 tick-to-order 测量，不能验收 1ms/5ms 目标、500 合约/20 策略的上限，也不能据此决定 colo。目标主机、真实行情工作量和存储失效范围仍待原架构问题验证。

归档按[明确运行清单](remote-commit-selection.json)复制，未按目录时间猜测最新结果。[归档索引](evidence/remote-commit-archive-index.json)及[最终独立复核](evidence/remote-commit-verification.json)记录 4,531 个原始文件、40,035,321 字节的哈希核对、两份最终构建内三组 QUIC 原始运行的逐事件重算与 18 档矩阵的逐事件重算。归档增加的索引/核验文件另行计数，不伪称为运行时原始记录。
