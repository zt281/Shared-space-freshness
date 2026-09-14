# Tyche 期权做市算法讨论交接

## 下一会话的任务

在 Tyche 仓库根目录与用户继续「期权定价、曲面拟合与参数状态」的 HITL 讨论。用户已有完整的期权做市波动率拟合算法，并明确将这块留给另一个 Agent。先认领问题，再请用户提供已有算法的描述或资料位置；不要替用户选择模型或代答其算法设计。当前阶段只形成架构决定，不直接实现生产代码。

## 入口与主记录

- [目标问题及交接边界](../tyche-architecture/issues/14-option-pricing-model.md)：包含尚未接受的 Q50–Q52 建议。问题已释放认领，仍 open；先按本地约定认领，完成访谈后记录 Answer。
- [架构地图](../tyche-architecture/map.md) 与 [追踪约定](../tyche-architecture/README.md)：按需加载依赖，地图只保存索引，非研究问题一次解决一个。
- [领域术语](../../CONTEXT.md)：新术语确定后及时记录。

## 按问题取用的背景

- 算法输入、事件触发及容量约束：[策略运行与性能预算](../tyche-architecture/issues/04-strategy-performance.md#answer)。
- 插件、共享空间及恢复契约：[部署决议](../tyche-architecture/issues/01-deployment-lifecycle.md#answer)、[共享空间 ADR](../../docs/adr/0002-unified-shared-space.md)。
- 合约、数量、币种、时间及归属：[领域模型](../tyche-architecture/issues/06-market-domain-model.md#answer)。
- 关键定价结果失效及执行门槛：[订单执行契约](../tyche-architecture/issues/07-order-risk-recovery.md#answer)。
- 参数编辑/批量提交/冲突：[工作台决议](../tyche-architecture/issues/05-workbench-workflow.md#answer)。
- 需要你的结果作为输入：[定价性能原型](../tyche-architecture/issues/15-pricing-capacity-prototype.md)、[后端架构](../tyche-architecture/issues/08-backend-architecture.md)、[历史数据契约](../tyche-architecture/issues/19-factor-history-contract.md)。

## Suggested skills

使用 `wayfinder`、`grill-with-docs`（含 `grilling` 与 `domain-modeling`）；设计插件契约时使用 `codebase-design`。需要外部模型事实时使用 `research`，需要可运行实验时按已授权的 `prototype` 流程单独处理。问题提到的 `engineer-cpp-option-market-making` 与 `engineer-hft-cpp-platform` 在本会话检查的本地技能目录中未找到；若下一会话可用可读取，不能假装已应用。

## 协作注意

开始前检查 `git status --short`，阅读当前工作区的最新文档并保留其他人的改动。此前架构讨论已提交并推送，后续仍可能有并发变更。`.codegraph/` 存在，但本会话 `codegraph` 命令不可用；下一会话先按 AGENTS.md 尝试探索，仍不可用再读文档。本会话将推进其他问题；避免覆盖并发修改，新的模型事实与结论保存在目标问题，地图只补摘要指针。
