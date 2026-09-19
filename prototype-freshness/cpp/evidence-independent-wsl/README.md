# 独立进程挂接与发布者接管证据

2026-09-19。基线来自用户提供的 [Shared-space-freshness](https://github.com/zt281/Shared-space-freshness)，原提交 `21720e963b0f4306913836c61ddfe72737b032ee`，保留在独立原型分支。主工作区的架构问题继续保持 claimed，本轮不等于全部共享空间设计已验收。

## 最终验证

| 构建 | 原快照/恢复 44 项 | 原逐笔消费 38 项 | 新独立启动/接管 69 项 |
| --- | --- | --- | --- |
| Debug | [摘要](debug/ctest-evidence-e0749c545aa7/summary.json) | [摘要](debug/ctest-evidence-f688c6f94a02/summary.json) | [摘要](debug/independent-evidence-2da675cc6078/summary.json)、[逐项结果](debug/independent-evidence-2da675cc6078/results.jsonl) |
| UBSan | [摘要](ubsan/ctest-evidence-999ad563050e/summary.json) | [摘要](ubsan/ctest-evidence-5d7dce26cfa6/summary.json) | [摘要](ubsan/independent-evidence-6f8667ceeb1e/summary.json)、[逐项结果](ubsan/independent-evidence-6f8667ceeb1e/results.jsonl) |

每种构建均通过 151 项检查。历史 68 项新场景试运行及其源码也保留，最终结果以上表为准，不将重复运行累加为独立检查数量。普通/UBSan 两套目录各有 21,795 条 JSONL 记录（含历史试运行、原回归与控制证据）；不是行情数量或性能采样数量。

当前实测环境为 Ubuntu 24.04.4 LTS / WSL2 x86_64、GCC 13.3.0、CMake 3.28.3、Python 3.12.3。构建和二进制哈希见 [Debug 元数据](debug/build.json) 与 [UBSan 元数据](ubsan/build.json)，最后一次 CTest 完整输出分别保存在同目录 `LastTest.log`。UBSan 启用 `-fsanitize=undefined -fno-sanitize-recover=all -fno-omit-frame-pointer`。逻辑毫秒为实验注入，订单及业务核对为模拟。

## 本轮观察

- 发布者与两消费者通过全新程序启动、各自 `shm_open` 挂接；映射地址实际为 `0x310000000000`、`0x320000000000`、`0x330000000000`。独立核对 PID、区域身份及逐条载荷；不依赖继承业务映射或原生指针。
- 未创建、未初始化、长度不兼容、错误区域身份、错误日志身份、重复创建和地址冲突均被拒绝。读者不能通过正常 interface 发布，发布者不能直接调用旧实验的 restart 接口绕过接管。
- 活跃发布者、被 SIGSTOP 暂停的发布者、以及关闭文件锁但进程仍存活的发布者，都阻止替代者接管。超时会限制依赖路径，不能用作已退出证明。正常退出及发布临界区外的 `_exit(77)` 之后，替代进程可取得新代次。
- 发布者经历四个代次，日志序号保持连续；两个消费者分别处理全部 16 条事件，逐条序号、seal 和完整业务字段匹配。慢组保留原 cursor，从完整日志补回 5 条已被 8 条共享缓冲挤出的旧代次事件。
- 旧进程崩溃前确有尚未发布的私有草稿；新进程不能继承它，也不能用普通发布替代接管所需的完整来源快照。旧恢复核对凭据、旧代次意图和结果未知的意图不被重新放行或重复提交。
- 新独立消费者必须完成启动核对与 200ms 演示稳定期。接管恢复同样保留事件补齐、核对、稳定期和主动停止门槛。转发旧记录/普通心跳不更新业务核验时间。
- 修正 `OrderedConsumer` 的诊断遗漏：即便首次看见新代次时已有有效快照，也标记 recovering 并记录告警/模拟撤余，与已有关闭交易门槛的行为保持一致。

证据中的 stdout 是供实验调度器保存和核对的观察；它不向消费者传递业务输入。消费者实际数据仍经 `Space` 的共享区域和日志读取。

## 证据完整性与复现

每个新场景目录包含逐进程命令、完整状态/事件、进程启动及退出、故障注入、stderr、本地二进制实验日志、源码快照、源码/二进制哈希和摘要。`sources/` 记录对应运行的源码，不用最终代码冒充历史试运行代码。

可在 Windows 或 Linux 离线重验保存的 JSON、源码哈希、三进程不同地址和两消费者完整事件：

```bash
python prototype-freshness/cpp/evidence-independent-wsl/audit.py
```

[audit.json](audit.json) 保存解析结果和全部证据文件的 SHA-256。该审计已通过；两次最终新场景的 stderr 均为空。

重新执行全部实验的方法见上级 [README](../README.md)。指定持久证据父目录的示例（从原型仓库根目录执行）：

```bash
cmake -S prototype-freshness/cpp -B prototype-freshness/cpp/build-independent \
  -DCMAKE_BUILD_TYPE=Debug \
  -DPROTOTYPE_EVIDENCE_ROOT="$PWD/prototype-freshness/cpp/build-independent/evidence"
cmake --build prototype-freshness/cpp/build-independent --parallel 3
ctest --test-dir prototype-freshness/cpp/build-independent --output-on-failure --verbose
```

UBSan 使用另一构建目录并增加上面记录的 CXX_FLAGS；每次生成新的证据子目录。不要覆盖本页已归档目录。

## 事实依据和证明范围

本机不同进程可通过名称打开同一 POSIX 区域；删除名称后再创建同名对象会得到新对象，这也是区域身份不能只取名称的依据。[Linux shm_open](https://man7.org/linux/man-pages/man3/shm_open.3.html)

实验用 `MAP_FIXED_NOREPLACE` 验证不同基址并拒绝冲突，仍检查实际返回地址。[Linux mmap](https://man7.org/linux/man-pages/man2/mmap.2.html)

文件锁只协调合作调用者，而且可因关闭描述符而释放，不能单独作为进程退出证明；本轮另用 pidfd 和进程启动身份核对前任退出。无法验证时不接管。[Linux flock](https://man7.org/linux/man-pages/man2/flock.2.html)、[pidfd_open](https://man7.org/linux/man-pages/man2/pidfd_open.2.html)、[proc_pid_stat](https://man7.org/linux/man-pages/man5/proc_pid_stat.5.html)

这些机制仅是本地原型候选，不是生产注册、认证、跨节点仲裁或自动运维服务。场景由调度器启动替代进程，准入由共享空间复核；没有部署常驻守护进程或连接真实账户。接管共享区仍存在，日志使用本机固定二进制布局，文件 I/O 仍在共享锁内。未验证写日志与发布之间崩溃、进度持久化、整机掉电、磁盘实际故障、恶意进程、全量故障事件、旧映射仍存活时同名区域重建、Windows 原生或跨境性能。

后续优先回答：完整记录已写而 head 尚未发布时崩溃，应如何区分已提交与尾部未提交记录；消费者进度如何与业务处理结果一起恢复。这些不能由本轮“发布临界区外退出”实验推断。
