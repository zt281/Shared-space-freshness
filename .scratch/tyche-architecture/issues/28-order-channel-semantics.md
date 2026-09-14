# CTP 与 Binance 的订单回报、撤单和保护能力

Type: research
Labels: wayfinder:research
Status: resolved
Assignee: codex-order-facts
Parent: ../map.md
Blocked by: none

## Question

为 [订单、风控和恢复语义](07-order-risk-recovery.md) 补齐第一方事实。复用已有研究，聚焦 CTP、Binance USDⓈ-M（含股票永续）及普通 Options：报单本地返回/受理/成交的区别、报单查询与客户标识、未知结果和重试/幂等边界、部分成交及撤单竞争、撤改/批量的原子性、成交去重/重连恢复、MMP与倒计时撤单的产品/权限范围和续期条件。

明确原生保护和 Tyche 本地停止发单的不同，普通 API key 不代表特殊保护权限。当前 SDK/账户/接口无法核实的内容标明，不能给出跨交易所 exactly-once 或原子双边成交保证。输出紧凑可操作语义表与接入验收清单，不写完整接口手册，不访问凭据、不签协议、不下单。

资产 ../research/order-channel-semantics.md；研究分支 research/order-channel-semantics。

## Resolution

公开接口事实已核实，详见 [订单通道语义研究](../research/order-channel-semantics.md)。未知结果不代表失败；撤单不回滚成交；客户单号不是永久幂等保证；批量不保证双边原子成交。原生断线保护的权限、作用域和续期逐产品区分。CTP SDK/柜台以及个人账户的具体能力仍需接入验收，未访问账户或下单。

Context: research/order-channel-semantics @ c610811；资产 `.scratch/tyche-architecture/research/order-channel-semantics.md`。
