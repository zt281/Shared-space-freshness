# 前端模块、状态同步与渲染路径

Type: grilling
Labels: wayfinder:grilling
Status: open
Assignee: none
Parent: ../map.md
Blocked by: 05, 08, 11, 18

## Question

Electron、TypeScript 和 Vue 如何划分桌面能力、连接管理、业务状态及视图职责？结合后台接口和工作台负载，确定快照与增量同步、断线恢复、行情更新调度和大列表渲染方案，并明确交易凭据与下单能力的权限边界。

将工作台原型验证出的容量和交互边界作为输入，明确面板类型目录与面板实例、工作区持久化、合约联动和独立操作对象的接口；参数草稿/生效版本、跨窗口状态与请求结果不能各自成为互相冲突的权威来源。历史查询、实时订阅及告警契约与后台职责对齐。
