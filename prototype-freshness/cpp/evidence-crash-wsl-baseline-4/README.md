# 基线崩溃窗口反例

在未修改的 `0d33ccf` worker 上，通过仅注入该实验发布者的 `LD_PRELOAD`，在第二次 `fdatasync` 成功后、返回 `Space::append` 前 `_exit(77)`。正常退出后另行重启消费者，观察内存进度及主动停止是否保留。12 项观察全部符合基线反例预期，不是新恢复功能验收。

- `journal_after_crash.bin/jsonl`：完整序号 2、旧代次 1、业务时间 410；共享 head 仍为 1。
- `journal_after_replacement.bin/jsonl`：同一序号被新代次 2、业务时间 420 的记录覆盖；旧事件从未交付。
- 两份 reader JSONL：旧进度 1，重启进度 0，首条被再次处理；重新核对后，旧主动停止消失。
- `publisher_before_crash.stderr.txt` 中一行故障注入说明是预期输出，退出码为 77。

`manifest.json` 保存基线代码身份、worker/注入库/解码器哈希和源码。worker 来自上一轮 Debug 构建，源码对应 `sources/` 内的 `0d33ccf` 文件；诊断辅助程序额外保存。辅助二进制用以下命令构建，然后运行 `crash_baseline.py` 的 usage 指定这三个二进制及新证据目录：

```bash
g++ -std=c++20 -Wall -Wextra -Wpedantic -Werror -fPIC -shared crash_baseline_fault.cpp -ldl -o crash_baseline_fault.so
g++ -std=c++20 -Wall -Wextra -Wpedantic -Werror journal_inspect.cpp -o journal_inspect
python3 crash_baseline.py BASELINE_WORKER CRASH_FAULT_SO JOURNAL_INSPECTOR NEW_DIRECTORY
```

这些命令在 `prototype-freshness/cpp` 目录执行；必须使用基线 worker，修复后的 worker 不应通过“尾部被覆盖”的观察断言。此前的 `evidence-crash-wsl-baseline/` 是解码器构建失败后的未完成准备；`baseline-2/`、`baseline-3/` 保留早期诊断失败，原因是断言比较了观察时点等诊断字段，后来改为比较规范化业务载荷。它们不计作基线结果或恢复通过。
