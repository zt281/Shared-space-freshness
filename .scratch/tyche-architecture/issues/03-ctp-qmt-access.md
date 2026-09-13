# CTP 与 QMT 的接入和运行约束

Type: research
Labels: wayfinder:research
Status: resolved
Assignee: research-ctp-qmt
Parent: ../map.md
Blocked by: none

## Question

CTP 和 QMT 接入中国期货期权、股票交易的官方开发接口、授权前提、运行系统和进程依赖是什么？尤其核实 C++ 能直接接入的部分，以及 QMT、MiniQMT、XtQuant 各自的角色。分清公开接口与需券商或供应商确认的能力，为 C++ 后台的部署和适配方式提供依据。

## Answer

2026-09-10：完成公开第一方资料调查，结论、来源和抓取限制见 [CTP 与 QMT 接入边界调研](../research/ctp-qmt-access.md)。研究保存在 `research/ctp-qmt-access`，提交 `d9fe7e015273b016e76760ab1a6936b2e5f3e48c`。

CTP 有 C++ 与 Windows/Linux SDK，行情和交易连接分别管理，具体版本与认证须匹配接入方。QMT 已核实的公开接口为 XtQuant Python，交易依赖 MiniQMT；用户可获得的原生 C++ SDK 与 Linux 无界面交易部署尚未得到证实。客户端运行、券商授权和行情订阅能力会影响后台拓扑。

下一步由 [QMT 的接入路径与 C++ 边界](13-qmt-language-boundary.md) 决定候选路线。研究没有授权采用 Python 桥，也没有验证任何实盘权限或性能。
