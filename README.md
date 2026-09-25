# Tyche

个人多账户交易工作台：C++ 后台，Electron + TypeScript + Vue 桌面；目标包含 CTP
期货期权及已选 Binance 产品。当前已完成开发准备，仓库保留设计与原型，正式应用尚未实现。

## 开始开发

- [开发就绪说明与剩余验收门槛](.scratch/tyche-v1/README.md)
- [首版实现规格](.scratch/tyche-v1/spec.md)
- [按依赖排列的 25 个实现任务](.scratch/tyche-v1/ticket-index.md)
- **先做：[回放行情进入只读桌面](.scratch/tyche-v1/issues/01-replay-desktop.md)**，无账户或算法源码依赖。

不再以额外原型作为开工前提。完整链路检查点合批与容量测试已经进入实现任务的验收条件。
实际账户权限、双屏和部署主机测试是相关功能上线门槛，不是基础代码开工门槛。

## 仓库内容

- `.scratch/tyche-v1/`：当前规格、开发顺序和逐项验收条件。
- `.scratch/tyche-architecture/`：历史决策问题、调研和讨论证据。
- `docs/adr/`、`CONTEXT.md`：已接受的架构取舍和领域术语。
- `prototype-freshness/`：历史共享空间与 QUIC 原型及原始证据，不是生产应用。

生产代码按后台、桌面、行为测试与资源分组；首个实现任务建立实际目录，并在此记录准确的
安装、构建、运行和测试命令。工具基线为 C++20/CMake、Node 22/npm、Python 3.9+；
依赖的准确版本及锁文件由首个实现任务提交。当前尚无正式应用启动命令。

## 复查原型

现有 Linux C++ 原型需要 C++20 编译器、CMake ≥3.20、Python ≥3.9 和 pthread：

```sh
bash prototype-freshness/cpp/run.sh
```

详见 [C++ 原型说明](prototype-freshness/cpp/README.md)。QUIC 的额外依赖按其独立说明准备。
消费检查点实验单独保存在 `prototype/consumer-checkpoint-recovery` 分支，工作台原型在
`prototype/workbench` 分支。原型结果不等于生产延迟、真实账户能力或实盘授权。
