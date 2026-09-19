# MsQuic 可靠流、本地持久副本与恢复：证据

2026-09-19。本轮接受 Q8 的 MsQuic 原型及 Q9 的远端先保存再发布。运行真实本机 UDP/QUIC，固定 MsQuic v2.6.1 C API + 私有 QuicTLS；源码、协议和命令见 [QUIC.md](../QUIC.md)，下载/构建来源另见[依赖证据](../evidence-msquic-build-wsl/README.md)。没有实盘调用或物理双机测试。

## 最终行为验证

| 明确运行身份 | 运行时日志/检查点路径 | 全部 CTest | QUIC 新场景 |
| --- | --- | --- | --- |
| `debug-ext4-23d99c47d68c` | WSL 原生 ext4，结束后逐文件复制到本目录 | 6/6，原 499 + 新 124 = 623 项 | `quic-evidence-6840c1ab91e2`，14 场景、124 项 |
| `ubsan-0c8c160c520f` | D 盘 NTFS / DrvFs(9p) | 6/6，同样 623 项 | `quic-evidence-02b40afd4573`，14 场景、124 项 |

Debug `quic_worker` SHA256：`14eb6f222839c694a8082dc0a05027877b57cb8cd353ec98a536d8d54da7dc54`。
UBSan `quic_worker` SHA256：`fb1e5ab109ac3327b7399a8a8623f580ab3c93f44e51344c58fc5a61ce192559`。
MsQuic 动态库 SHA256：`10d88b8fcdc411952430525bdc08885ca3b09899e371f2924f7c6c41bc516b7a`。

两个运行均保留源文件快照、实际 CMake/Ninja/编译命令、各 ELF 哈希、依赖路径、命令原始 stdout/stderr、CTest 日志和全部子进程启动/输入/输出/退出记录。UBSan 为 `-fsanitize=undefined -fno-sanitize-recover=all`，覆盖本项目 C++，不覆盖预先构建的 Release MsQuic/QuicTLS。不是 TSAN、内存分配失败或生产内存上限测试。

14 场景覆盖：按依赖复制与不同映射地址的独立消费者；多流到达次序和延迟控制屏障；新增订阅补齐；重复/同序冲突/旧代次/序号缺口自动补读；半帧断连与 stream reset；过长帧拒绝；远端四个写入/保存/发布崩溃点；保存错误；消费者检查点、停止和旧意图；提供者退出证明与来源 epoch；慢接收及有界缓冲；错误 pin、无客户端证书和错误 CA。源端、接收端和消费者都是独立 exec 进程。测试证书公钥和创建命令保留，私钥不在此目录。

同步门闩显示 `R=22, D=V=21` 时，完整第 22 条虽然已写入文件，独立消费者仍只能看到并处理前 21 条。完成同步再发布。完整但未返回的日志尾可恢复交付；半条尾原样保留并拒绝恢复。消费者 A 可落后于 V，审计只认可它已确认的准确前缀，不把停止消费者的未处理事件计为已完成。

## 失败与诊断没有被覆盖

`development/` 保留最初试验。初次消费者文件名没有 `PROTOTYPE-` 前缀而被既有保护拒绝，随后修正夹具；较早的恢复许可测试混用了实际启动时刻与逻辑事件时刻，因稳定期或正确的业务过期限制而失败。`debug-aab40cf7d1b3`、`ubsan-22955e526989` 的相同时间问题也保留。最终显式提供消费者 `START_TICK=0`，各行为步骤使用逻辑时刻；没有延长业务有效期或取消核对。

源代码复核还修正了跨流屏障校验：数据可能先于较早的控制屏障到达，不能因为 `D > B` 就拒绝正确屏障。接收字节预留改用原子比较交换，避免不同连接回调同时越过应用额度。前后成功运行全部保留，但最终结论仅引用上表固定运行身份。

**已有检查点替换错误在本轮再现两次，尚未修复或接受该保存路径：**

| 运行 / 场景 | 真实结果 | 独立字节核验 |
| --- | --- | --- |
| `ubsan-8d959e8aef21` / `recovery-evidence-721601d2b825/checkpoint-4` | 旧错误文本 `replace complete checkpoint`，当时未捕获 errno | 权威日志 13 条；已提交 checkpoint revision 7 / cursor 5；完整 pending revision 8 / cursor 6 未提交；消费者受限 |
| `debug-b425f91fc1a1` / `recovery-evidence-68a92d3be1d9/checkpoint-6` | 新诊断明确 `errno=13: Permission denied`，发生在首次消费保存的 rename | 权威日志 1 条；checkpoint revision 1 / cursor 0；完整 pending revision 2 / cursor 1 未提交；消费者受限 |

见 `checkpoint-replacement-failure.json` 与 `checkpoint-replacement-eacces.json`。原始文件未截断、未提升 pending、未加自动重试。`durable_consumer.cpp` 仅补立即捕获 errno 的失败诊断，原成功/失败语义不变。错误发生后的只读权限核验：目录 Linux mode 755、文件 600，属当前 alan；Windows 文件为 Archive 而非 ReadOnly，目录 ACL 含 Authenticated Users 的 Modify。这不能排除故障瞬间的占用/权限变化，也不能证明 Windows 具体哪个组件导致失败。

`diagnostic/checkpoint-repeat-1d3f08e96fd3` 使用已加 errno 的 UBSan 二进制，按真实 checkpoint-4 路径做 40 次有限复验，共约 54.57 秒，没有重现。之后完整 Debug 回归才在另一个 checkpoint-6 路径捕获到 errno 13。未取得稳定的最小复现，也没有根因结论。最终 Debug ext4 与失败的 D 路径使用同一二进制；ext4 通过和后来 D 路径 UBSan 通过都不能抹去间歇失败，不能据此断言 ext4 一定可靠或 DrvFs 是根因。

## 独立核验与复现

`quic_evidence_audit.py` 不读取运行时共享内存。它按固定大端格式重新解码远端日志，对照独立解码的 96 字节源日志，核对序号、全部载荷、seal、半条尾，以及每个 128 字节检查点的身份、累计和、顺序摘要和已确认进度；另检查模拟外部提交次数、退出码、构建/运行源码一致性与最终二进制身份。

```sh
python3 quic_validate.py debug --storage ext4
python3 quic_validate.py ubsan
python3 quic_evidence_audit.py debug-ext4-23d99c47d68c ubsan-0c8c160c520f
```

新验证生成新的运行身份；审计时应传入要核验的明确目录，不按 mtime 选“最新”。`audit.json` 保存上述最终运行的逐对象核验和全部保留文件 SHA256；原始字节通过本目录 `.gitattributes` 保留。

本轮没有吞吐、1ms/5ms 目标、500 合约/20 策略真实计算、主机掉电恢复或 colo 必要性的结论。控制台与文件记录有额外成本，当前网络只是回环。用户随后已选在当前电脑继续合成网络扰动；该实验与本轮行为证据分开保留，且不把配置的延迟/丢包当作真实跨境测量。
