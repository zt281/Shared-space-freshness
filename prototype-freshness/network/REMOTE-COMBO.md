# QUIC 源端批量 × 远端有界保存组合对照

本轮回答：源端以 `batch` 模式成批提交后，突发真正成批抵达远端，远端三种保存模式（`sync`/`worker`/`batch`）在可比负载下的行为差异；以及更重负载下远端队列真正积压时，合批是否减少远端同步次数并改善尾部。本轮**没有新的语义取舍**：有界队列、队满受限断连、先保存后发布、D/V 一起推进、消费者逐事件检查点全部沿用 [REMOTE-COMMIT.md](REMOTE-COMMIT.md) 与 [SOURCE-COMMIT.md](SOURCE-COMMIT.md) 的边界。队列/合批参数仍为实验值（64/8/2ms）。这是当前 Windows/WSL 的有限原型实验，不是正式存储、网络或策略容量验收。

## 设计

**可比主块（18 档）**：源端固定 `TYCHE_QUIC_SOURCE_MODE=batch`（64/8/2ms），远端 `TYCHE_QUIC_REMOTE_MODE=sync|worker|batch` × 平稳(40/s,2s)/突发(80/s,1s，每 100ms 8 条) × 3 轮轮换顺序（`sync/worker/batch`、`worker/batch/sync`、`batch/sync/worker`）= 18 档、1,440 条，结构与上轮远端矩阵可比。

**重压附加块（9 档，新条件，不与主块直接可比）**：200/s、每 100ms 突发 20 条、持续 1 秒，每档 200 条 + 2 条初始化；源端 batch × 远端三模式 × 3 轮轮换 = 9 档、1,800 条。目的是让远端队列深度显著大于 1。排空时若连接因队满/反压关闭且非保存失败，探针按既有语义重连（接收端保留订阅 mask，从持久游标补读）并记录重连次数；保存失败不重连。全部拒绝、未完成、受限与过期观察均保留。

同一 Release 二进制（与上轮 remote-commit 逐位相同）、直接本机回环（profile=direct）、运行时日志在 WSL ext4、每档最多 12 秒排空、迟到不后移计划、trace 旁路开启。基准期间不并行其他构建/审计。仅 80/200 个观测时最近秩 p99 等于最大值，不能据此验收生产尾分位数。

本轮没有改任何 C++ 或场景代码，只新增测量脚本（`remote_combo_probe.py` 等）并给 `stage_probe.py` 增加可选的排空期重连记录（默认关闭，旧行为不变）。按纪律仍重跑了 release 全量 CTest 确认基线未退化。

## 复现

```sh
python3 stage_validate.py release --series remote-combo
python3 remote_combo_probe.py --worker /home/alan/.cache/tyche-prototypes/quic-20260919/remote-combo-release/quic_worker \
  --evidence-root /home/alan/.cache/tyche-prototypes/quic-20260919/remote-combo-network
python3 stage_audit.py /absolute/path/to/combo-matrix-evidence
python3 remote_combo_probe.py --worker /home/alan/.cache/tyche-prototypes/quic-20260919/remote-combo-release/quic_worker \
  --evidence-root /home/alan/.cache/tyche-prototypes/quic-20260919/remote-combo-heavy --heavy
python3 stage_audit.py /absolute/path/to/combo-heavy-evidence
python3 remote_combo_verify.py   # 归档后在仓库证据树上总复核
```

## 最终结果

基线重跑 [Release](evidence/remote-combo-release-7e0d40a79345/manifest.json) **8/8 CTest、959 项检查通过**；worker SHA256 `fffe5106df8d2ec0ea4a8197030b6b4c53c9d84ef15e238a14a6bcb7bf73ab23`，与 remote-commit 轮最终二进制逐位一致（源码未变）。依赖仍为固定 MsQuic v2.6.1，库 SHA256 `10d88b8fcdc411952430525bdc08885ca3b09899e371f2924f7c6c41bc516b7a`。

[主块 18 档](evidence/remote-combo-matrix-848eb4898151/manifest.json) **1,440/1,440 全部完成**，[重压块 9 档](evidence/remote-combo-heavy-28056a84d957/manifest.json) **1,800/1,800 全部完成**；无拒绝、无未知结果、无旁路溢出、**未触发队满断连（0 次重连）**。两块均通过 [stage_audit](evidence/remote-combo-matrix-848eb4898151/stage-audit.json) 逐事件核对（[重压块审计](evidence/remote-combo-heavy-28056a84d957/stage-audit.json)）。

### 主块突发档（80/s，每 100ms 8 条；计划至内部完成）

| 轮次 | 模式 | 窗口内完成 / 80 | 中位数 ms | 最大 ms | 远端同步次数 | 远端 max_pending | 源端同步次数 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | sync | 64 | 185.76 | 277.90 | 82（逐条） | — | 20 |
| 1 | worker | 66 | 177.57 | 299.85 | 82 | 4 | 20 |
| 1 | batch | 72 | 121.69 | 208.26 | 41 | 4 | 20 |
| 2 | worker | 66 | 166.99 | 237.58 | 82 | 4 | 20 |
| 2 | batch | 72 | 127.22 | 186.74 | 40 | 4 | 20 |
| 2 | sync | 8 | 2,716.30 | 4,617.91 | 82（逐条） | — | 14 |
| 3 | batch | 16 | 1,912.94 | 1,996.38 | 38 | 4 | 20 |
| 3 | sync | 65 | 147.71 | 239.16 | 82（逐条） | — | 20 |
| 3 | worker | 72 | 130.54 | 199.52 | 82 | 4 | 20 |

源端合批生效（突发档源端同步 80→20 次），突发真正成批抵达：远端队列 `max_pending` 达 4（上轮源端 sync 时恒为 1）。**干净的第 1/2 轮中远端合批首次测出收益**：远端同步次数 82→40/41，窗口内完成 72/80 对 sync/worker 的 64–66/80，中位数 121.69–127.22ms 对 166.99–185.76ms。worker 与 sync 的总时长接近——远端磁盘等待移出应用线程但每条仍各付一次 fdatasync。

**第 2 轮 sync 档与第 3 轮 batch/sync 平稳档撞上宿主存储/调度停顿**（这些档 `replica_fdatasync` 中位 29–65ms，正常 8–12ms；2-轮 sync 档发送至接收回调中位 629.39ms 显示接收反压经流控回传；分别保留 51、4、29 条过期观察，消费者均未放行）。这些档未通过调参或重试掩盖，原始记录保留；它们不与干净档混成分位数，也不据此宣称任何固定收益。平稳干净档三模式几乎无差别（中位 45.49–49.01ms）。

### 重压块（200/s，每 100ms 20 条；新条件）

| 轮次 | 模式 | 窗口内完成 / 200 | 中位数 ms | 最大 ms | 远端同步次数 | 远端 max_pending |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | sync | 51 | 961.89 | 1,701.76 | 202（逐条） | — |
| 1 | worker | 49 | 881.45 | 1,663.06 | 202 | 24 |
| 1 | batch | 60 | 779.06 | 1,483.49 | 58 | 10 |
| 2 | worker | 53 | 1,005.10 | 1,671.43 | 202 | 21 |
| 2 | batch | 60 | 750.35 | 1,405.41 | 60 | 10 |
| 2 | sync | 66 | 867.22 | 1,577.83 | 202（逐条） | — |
| 3 | batch | 60 | 724.42 | 1,419.18 | 59 | 10 |
| 3 | sync | 56 | 968.26 | 1,738.82 | 202（逐条） | — |
| 3 | worker | 54 | 821.61 | 1,622.04 | 202 | 20 |

远端队列真正积压（worker `max_pending` 20–24，batch 10；上限 64 未触及）。**合批收益在重压下明确**：远端同步次数 202→58–60（平均每次同步约 3.4 条），远端队列等待中位数从 worker 的 95.07–117.57ms 降到 batch 的 5.55–6.41ms；窗口内完成 batch 稳定 60/200，优于 sync 51–66 与 worker 49–54；整轮中位数 batch 724.42–779.06ms 对 sync 867.22–968.26ms、worker 821.61–1,005.10ms。sync 模式的接收串行保存经流控回传（发送至接收回调中位 367.59–435.44ms），并留下 5/5/7 条过期观察（未放行）。

**尾部主力已不是远端保存**：所有重压档 `V→consumer_begin` 中位 220.57–857.66ms——消费者逐事件检查点（每事件约 10ms 同步）在 100 条/秒/对象的到达率下饱和，这是本轮固定未改的条件，也是下一轮最明确的候选。

## 限制与下一步

- 重压块是新条件（200/s、突发 20），不与 18 档主块及历史矩阵直接可比；9 档样本小，宿主未隔离。
- 主块第 2/3 轮的停顿档保留原样；各次单调时钟只在本次运行内关联，不跨运行拼接。
- 本轮未触发队满断连，恢复路径（重连补读）在负载下未被 exercise——仅由 remote-commit 轮的 overflow 场景覆盖；如需负载下队满证据，需要更激进档位或更小容量。
- 消费者逐事件检查点仍是固定条件；其饱和已成为尾部主力，但是否改变消费者提交/恢复边界需另行明确取舍。
- 64/8/2ms、每日志一线程仍为实验参数；本机 WSL 回环、单一宿主的存储特性不能外推生产。

归档按[明确运行清单](remote-combo-selection.json)复制。[归档索引](evidence/remote-combo-archive-index.json)及[最终独立复核](evidence/remote-combo-verification.json)记录 3,121 个原始文件、58,149,534 字节的哈希核对、基线构建内三组 QUIC 原始运行的逐事件重算与两块共 27 档 3,240 条的逐事件重算。归档增加的索引/核验文件另行计数，不伪称为运行时原始记录。
