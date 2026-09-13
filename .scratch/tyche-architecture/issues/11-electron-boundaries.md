# Electron 多窗口的数据与权限边界

Type: research
Labels: wayfinder:research
Status: resolved
Assignee: research-electron
Parent: ../map.md
Blocked by: none

## Question

Electron 官方对 main、preload、renderer、多窗口 IPC 与独立后台进程提供哪些边界和限制？哪些机制支持多个交易窗口共享后台状态而不把凭据或任意系统能力暴露给视图？核实 Vue 官方关于大量实时状态和大型列表的性能建议，并说明这些事实对行情显示路径的约束；不要据此宣称已经达到某个延迟或吞吐指标。

## Answer

2026-09-10：完成六个官方文档页面的核实，结论和来源见 [Electron/Vue 多窗口交易台技术边界](../research/electron-boundaries.md)。研究保存在 `research/electron-boundaries`，提交 `255145b30c30950ca9a5d1dd62f917c8c406de58`。

Electron 内部进程通信与独立 C++ 后台协议应分别讨论；utilityProcess 的 Node 脚本入口不能当成独立 C++ 服务的部署保证。多窗口需要明确状态同步；Vue 的虚拟列表、稳定属性和浅响应式是可评估手段，不构成本项目负载下的性能证明。

报告中的候选方案与测试口径交由 [前端模块、状态同步与渲染路径](09-frontend-architecture.md) 结合负载选择。
