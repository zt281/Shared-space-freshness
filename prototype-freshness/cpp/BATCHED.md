# 有界批量保存实验（可丢弃原型）

问题：保留完整日志恢复、确认保存后发布和逐事件检查点的规则，批量写入移出共享读锁是否改善读者连续性？

答案限定为本机实验：独立读进程在批量写线程停于同步阶段时仍可读取旧的完整 head、快照及历史前缀；一次同步可确认多个有确定身份的事件。短测中读锁等待下降，但整轮完成时间没有一致改善，且观测到一次检查点替换失败和明显短时漂移。不能据此确认生产容量、批量参数或目标存储。数值及完整证据见 [evidence-batch-wsl/README.md](evidence-batch-wsl/README.md)。

## 写入与读取的边界

`BatchPublisher` 是本轮的单进程、单接纳方、有界队列；它只服务一个已经初始化的具名 `Space`。容量包含排队及正在写盘的请求。请求进入队列前固定全局序号、代次、版本和完整载荷 seal，排队后不更改身份、不重排、不合并必需事件。已有版本或日志位置被同步入口推进时，旧提议在写入前明确拒绝，不重新编号。

具名写入口的固定顺序为本地写侧 mutex → 共享 robust Guard。旧 `prepare/publish/replace/verify/replay` 与队列的批量入口共用该写侧序列化；具名进程持有的日志 lease 及退出核验仍约束其他进程。继承到错误 PID 的具名写对象在碰本地 mutex 前被拒绝。旧匿名 fork 实验仍只用原有进程共享 Guard 覆盖整个写操作，不用进程内 mutex 冒充跨进程序列化。没有在活跃队列线程存在时 fork 的支持。

批量写入按以下顺序执行：

1. 短 Guard 检查已提交状态及全部提议，固定连续日志位置。
2. 释放 Guard，连续写入小批中的完整记录，只执行一次 `fdatasync`。仍持有写侧 mutex；读者不获取它。读者只看见旧完整的 head/ring/快照，不会从正在追加的尾部提前读取事件。
3. 保存确认后重新取得短 Guard，整批安装 ring/head 和最后一个完整快照。
4. 生成逐项最终结果。成功结果含原提议；发布时间不等于入队返回。

当前旧同步入口、接管扫描及 `read_after` 的历史文件补读仍在共享 Guard 内，未宣称全部磁盘等待已隔离。新 `Guard` 的单调时钟和原子计数有测量成本；性能对照使用同一个新 Release 二进制，不能直接把早期未计数二进制当作因果基线。

## 失败和恢复

`BatchState`：0 表示已拒绝且本批未开始写入，1 表示保存及共享发布均已确认，2 表示发生过写入尝试但结果未知。另用 `accepted` 区分接纳前拒绝与已接纳、尚未写入的队尾取消。尚未得到结果不算提交；unknown 不自动重发。

队满、过时提议或未完成必需输入会锁存独立的 `ingress_failed`。`View.validity` 因此为 gap，已提交 Record 的原始字段/seal 不改变。已接纳的连续前缀仍可排空、读取和审计；缺失输入使所有依赖该公共源的新指令受限。正常替换快照、解除主动停止或在同一共享区接管均不清除此缺口；实验没有自动修复入口。该标志只在本轮保留共享区域的范围内持久，未验证整机重启后的重建协议。

最终失败 receipt 可观察前先锁存公共受限状态。代码顺序审查确认：先停止接纳，释放队列 mutex，再拿共享 Guard 限制，最后完成失败 promise；没有拿队列锁等磁盘。场景在 `batch_drain` join 后检查结果与 gap，**不是专门复现等待首个失败 future 的竞态测试**。

写入/同步确认失败锁存 `record_failed`，保留原始完整或半条尾，不截断、不降级、不自动重试。旧写者确认退出后，完整且校验一致的日志仍是恢复依据：旧调用没有答复也可能在恢复同步后提交。接管不会让旧代次数据变新；新快照、补齐、当前核对、稳定期和主动停止等既有门槛不变。检测到的半条或记录/I/O 故障需要调查，不能靠接管自动修复。

新增共享字段使布局标识变为 **3**。相同尺寸的布局 1 和 2 均拒绝挂接；没有原地迁移或跨版本混用承诺。

## 有限故障检查

新增 14 个场景、120 个检查；每次最终 Debug/UBSan 运行均保留原 379 个检查，总计 499 个。故障注入为本地进程退出，不是断电证明。

| 退出位置 | 接管后的规则 |
|---|---|
| 批量写前 | 没有新记录交付 |
| 第一条完整、后续未写 | 完整前缀恢复并恰好交付该前缀 |
| 第一条完整、第二条半条 | 拒绝接管；原样保留尾部证据 |
| 全批完整、尚未同步 | 恢复同步确认后交付全批 |
| 同步后、共享发布前 | 从完整日志恢复全批 |
| 持 Guard 更新时快照撕裂 | robust owner-death 标为损坏，再从日志恢复 |
| 已共享发布、回复前 | 查证完整提议，不重发 |

其他场景包含：同步阶段门闩阻塞时独立读者仍读旧完整版本及归档前缀；旧 `verify` 与批量追加的写侧顺序；队列溢出；显式同步失败；多批顺序/环形覆盖；过时位置写前拒绝；旧布局拒绝。查询比对完整代次/版本/载荷/seal，不能只用 head 数值推断成功。

消费者每个事件仍保存 128 字节结果＋游标检查点，执行暂存文件写入、同步、原子替换、目录同步后才确认处理。没有检查点批量化，也没有真实交易副作用。

## 可复现命令

Ubuntu 中运行；Windows 可在这些命令前使用 `wsl -d Ubuntu --exec`。所有证据输出目录必须是新的。源码根为 `/mnt/d/dev/Tyche-freshness-prototype/prototype-freshness/cpp`。

```sh
cmake -S /mnt/d/dev/Tyche-freshness-prototype/prototype-freshness/cpp -B /home/alan/.cache/tyche-prototypes/batch-debug-20260919 -DCMAKE_BUILD_TYPE=Debug -DPROTOTYPE_EVIDENCE_ROOT=/mnt/d/dev/Tyche-freshness-prototype/prototype-freshness/cpp/evidence-batch-wsl/correctness
cmake --build /home/alan/.cache/tyche-prototypes/batch-debug-20260919 -j 4
ctest --test-dir /home/alan/.cache/tyche-prototypes/batch-debug-20260919 --output-on-failure
```

UBSan 构建使用独立 `batch-ubsan-20260919` 目录、`-DCMAKE_BUILD_TYPE=Debug -DCMAKE_CXX_FLAGS=-fsanitize=undefined -DCMAKE_EXE_LINKER_FLAGS=-fsanitize=undefined`，运行环境为 `UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1`。证据根单独指定 `correctness-ubsan`。Release 使用独立 `batch-release-20260919`、`-DCMAKE_BUILD_TYPE=Release`，实际参数 `-O3 -DNDEBUG`，无 sanitizer。

一个 10 ms 批量档的复现命令（曾一次发生检查点替换失败，一次无该错误但没能排空）：

```sh
python3 /mnt/d/dev/Tyche-freshness-prototype/prototype-freshness/cpp/capacity_run.py --binary /home/alan/.cache/tyche-prototypes/batch-release-20260919/capacity_probe --root /mnt/d/dev/PROTOTYPE-batch-new-run --rate 200 --fanout 1 --publisher-mode batch --seconds 2 --drain 3 --queue-capacity 128 --batch-size 8 --batch-wait-ns 10000000
```

同步对照改用 `--publisher-mode sync`，同一二进制、相同存储、输入率和消费者数。固定矩阵脚本为 `batch_capacity_matrix.py`；首次运行遇到真实失败而停止，`batch_capacity_followup.py` 完成剩余四档并仅复验一次。实际命令、UTC 时间及每次退出结果保留在证据 `capacity/matrix.json`、`capacity/followup-matrix.json` 和各档 `processes.json`。

离线复核（不会启动业务进程或更改原始日志/检查点）：

```sh
python3 /mnt/d/dev/Tyche-freshness-prototype/prototype-freshness/cpp/batch_evidence_audit.py /mnt/d/dev/Tyche-freshness-prototype/prototype-freshness/cpp/evidence-batch-wsl
```

`batch_evidence_audit.py` 在独立 `analysis/` 中生成汇总、整轮逐项时间及 100 ms 积压曲线。采样时的脚本/源码、原始 summary/hash 均保留；后处理版本单独记录。`audit_passed` 仅指已保存数据核对通过。
