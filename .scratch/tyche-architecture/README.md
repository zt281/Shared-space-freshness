# 架构讨论的本地追踪约定

入口为 [Tyche 多资产交易系统架构决策地图](map.md)。本目录采用 wayfinder 配套的 Local Markdown tracker；地图是索引，每个问题的细节只保存在对应问题单。

- 问题单位于 `issues/NN-slug.md`，编号从 `01` 递增。
- `Type` 表示 research、prototype、grilling 或 task；`Labels` 对应 `wayfinder:<type>`。地图使用 `wayfinder:map`。
- 本仓库补充约定：`Status: open` 表示待处理，`Assignee: none` 表示未认领。开始处理前同时改为 `Status: claimed` 并填写认领人。
- `Blocked by` 列出本目录的问题编号，`none` 表示无依赖。所有依赖均为 `resolved` 才可开始。
- 当前可处理问题：按编号扫描状态为 open、未认领、所有依赖均已 resolved 的问题单。
- 调研结果作为独立 Markdown 资产，问题单链接到它。结论追加在 `## Answer`，随后设为 resolved，并在地图追加标题链接和一句摘要。
- 用户讨论追加在 `## Comments`；建议与已确认选择应明确区分。绘图阶段的回答作为范围输入，不据此自动关闭后续架构问题。

绘制地图后，按当前可处理问题逐项讨论并记录结论。每次推进最多解决一个非 research 问题。研究问题可并行处理。
