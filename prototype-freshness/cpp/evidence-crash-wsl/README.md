# 发布提交与消费检查点恢复证据

2026-09-19，Ubuntu 24.04.4 LTS / WSL2 x86_64、GCC 13.3.0、CMake 3.28.3、Python 3.12.3。基线提交 `0d33ccf7eda70bd5d342b08839d3c13d3abfed37`。这是同机进程崩溃实验，逻辑时钟注入、核对及外部提交模拟。

## 最终结果

| 构建 | 原有快照、逐笔与独立挂接 | 新增恢复 | 完整运行与构建 |
| --- | --- | --- | --- |
| Debug | 44 + 38 + 69 项通过 | [23 场景、228 项](debug/recovery-evidence-7f8a0ae9c8b9/summary.json) | [CTest](debug/LastTest.log)、[元数据](debug/build.json) |
| UBSan | 44 + 38 + 69 项通过 | [23 场景、228 项](ubsan/recovery-evidence-5349ae3af885/summary.json) | [CTest](ubsan/LastTest.log)、[元数据](ubsan/build.json) |

每种构建均通过 **379 项不同检查**，不把重复运行相加。UBSan 实际编译参数包含 `-fsanitize=undefined -fno-sanitize-recover=all -fno-omit-frame-pointer`，全部目标启用 `-Wall -Wextra -Wpedantic -Werror`。`build.json` 将最终二进制哈希与对应恢复目录绑定。

目录同时保留两次早期 Debug 223 项试运行及其各自源码；后续增加了损坏 bool 表示和检查点空间身份的拒绝检查。整个目录的 41,577 条 JSONL 是实验状态/控制/逐事件记录，含重复运行，不是行情采样或性能样本。所有子进程 stderr 为空。

## 新覆盖的边界

- `publication-0..8`：日志写入前、半条写入、完整写入未同步、同步成功、缓冲写入、head 更新、快照撕裂、快照完整、已解锁但未答复。除半条尾记录保持受限外，全部按完整日志重建；新发布保留原日志前缀。两个存活消费者核对完整事件序列，慢消费者跨有限缓冲补读。
- `corrupt-*`：已公布历史短缺、序号/校验值损坏及无效 bool 表示均拒绝接管，原始故障文件保留，公共依赖受限。
- `checkpoint-0..6`：纯计算之后、暂存文件半条、完整写入、同步成功、替换当前文件、目录同步后和内存游标推进前退出。恢复的结果和游标始终一致，最终 13 条事件累计数量 91、价格 1391，顺序摘要逐条匹配；不重复计算已提交结果，也不跳过未提交事件。
- `control-7..8`：pending 意图重启后退役；unknown 在模拟外部提交前保存。在模拟提交前退出留下 0 次提交记录，在提交后退出留下 1 次，重启均不补发；未知结果不被普通恢复核对清除。
- `checkpoint-failures`：重复所有者、错误消费者/空间身份、缺失/半条/坏校验/超前/输入不符的检查点拒绝恢复。注入暂存文件创建失败后该组受限、没有模拟提交，公共日志及无关健康组继续。该故障是受控名称冲突，不冒充磁盘写满。

## 证据核对

每个场景保留命令、真实 PID/映射地址、完整事件和状态、退出码、故障时日志/检查点、最终日志/检查点及暂存文件。`sources/` 和 `manifest.json` 固定该次运行源码与二进制哈希。`audit.json` 记录 1,707 个原始文件的 SHA-256；独立 Python 解码器核对事件 seal/载荷、两个消费者的完整交付序列、检查点累计值、控制状态以及模拟提交数量。

```bash
python3 prototype-freshness/cpp/audit_crash_evidence.py prototype-freshness/cpp/evidence-crash-wsl
```

基线反例在相邻的 [baseline-4](../evidence-crash-wsl-baseline-4/README.md)。其 12 项检查确认旧实现的能力缺口，不纳入恢复验收数量。早期诊断目录也保留，详见该说明。

## 复现与限制

从独立原型仓库根目录运行：

```bash
cmake -S prototype-freshness/cpp -B prototype-freshness/cpp/build-recovery -DCMAKE_BUILD_TYPE=Debug
cmake --build prototype-freshness/cpp/build-recovery --parallel 4
ctest --test-dir prototype-freshness/cpp/build-recovery --output-on-failure
cmake -S prototype-freshness/cpp -B prototype-freshness/cpp/build-recovery-ubsan -DCMAKE_BUILD_TYPE=Debug -DCMAKE_CXX_FLAGS="-fsanitize=undefined -fno-sanitize-recover=all -fno-omit-frame-pointer"
cmake --build prototype-freshness/cpp/build-recovery-ubsan --parallel 4
ctest --test-dir prototype-freshness/cpp/build-recovery-ubsan --output-on-failure
```

检查点采用同一目录中的完整暂存文件及替换，依据 Linux [rename](https://man7.org/linux/man-pages/man2/rename.2.html) 的名称替换语义，并分别同步文件与目录；[fsync/fdatasync](https://man7.org/linux/man-pages/man2/fsync.2.html) 的完成边界不等于本实验已验证虚拟磁盘断电恢复。

仍未覆盖：主机重启/断电、共享区全部丢失后的代次恢复、坏日志修复、磁盘实际故障、任意策略状态和外部副作用事务、真实订单查询、跨节点、目标部署和生产容量。检查点每条同步、接管全日志扫描及共享锁中的文件 I/O 都只是语义候选。本轮不保证低延迟，也不是生产请求去重或存储协议。
