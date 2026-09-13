# 期权定价、曲面拟合与参数状态

Type: grilling
Labels: wayfinder:grilling
Status: open
Assignee: none
Parent: ../map.md
Blocked by: 04, 05, 06

## Question

已选择逐笔拟合并将其纳入完整报价反应链路后，首版需要哪些期权定价与曲面拟合方法、输入和有效性判断？按品种、期限和策略配置区分哪些参数与模型状态；同一行情触发多个策略时，哪些计算可共享，哪些必须保留独立结果？明确一次行情与其拟合结果、双边报价之间的版本和因果关系，以及拟合失败、行情不完整时交给策略/风控的可观察结果。

以 [运行与性能决议](04-strategy-performance.md) 和已确定的合约语义为约束，至少能为每组 100 个期权的双边报价准备有代表性的性能原型。此问题使用 grill-with-docs、domain-modeling、codebase-design 与 engineer-cpp-option-market-making；需要外部模型事实时另建有界 research 问题。

[工作台决议](05-workbench-workflow.md) 已要求 T 形报价展示并批量编辑逐合约参数。需要明确它与品种/期限参数的继承、覆盖和所有权关系，完整参数版本的原子范围、基于旧版本的提交冲突与生效回报，以及多个策略共享或独立使用参数时的区别。
