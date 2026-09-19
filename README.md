# Tyche：共享空间新鲜度原型分支

本分支 `prototype/shared-space-freshness` 保存可丢弃设计验证资产，不是正式应用。

- `prototype-freshness/index.html`：浏览器内逻辑演示，双击运行。
- `prototype-freshness/diagrams/`：三张中文职责与规则解释图。
- `prototype-freshness/cpp/`：Linux C++20 跨进程共享内存验证，含原始观察及可重复场景。
- `.scratch/tyche-architecture/`、`docs/adr/`、`CONTEXT.md`：此分支建立时的规划快照；最新决议以主工作区问题单为准。

运行 C++ 原型需要 Linux、C++20 编译器、CMake ≥3.20、Python ≥3.9 和 pthread；独立挂接场景还使用 Linux pidfd 与 MAP_FIXED_NOREPLACE：

```bash
bash prototype-freshness/cpp/run.sh
```

完整说明见 [C++ 原型说明](prototype-freshness/cpp/README.md)。当前程序不连接交易账户，不验证真实跨网络能力，也不包含生产容量承诺。
