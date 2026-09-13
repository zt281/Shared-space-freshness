# 部署边界与前端离线行为

Type: grilling
Labels: wayfinder:grilling
Status: open
Assignee: none
Parent: ../map.md
Blocked by: 03, 13, 23

## Question

桌面界面和交易后台分别需要在哪些操作系统、机器上运行？关闭界面、意外断连、整机退出应分别如何影响自动策略？明确后台独立运行的必要性、用户可提供的运行环境，以及后续故障处理讨论的场景。

## Comments

2026-09-10，建图访谈，用户确认：

- 前端关闭或失去连接时，后台继续运行，策略由独立的启停与风控规则管理。
- 使用 Windows 桌面；有或愿意使用 Linux／Windows 独立后台服务器。

仍需结合接入调研确定后台实际分布、通道进程位置及失联恢复场景。

[Binance 首版范围](12-binance-scope.md) 已将股票借券卖空移至另选通道；实际部署需纳入 [股票接入选择](23-stock-short-selling-access.md) 确定的网关、系统与运行依赖。
