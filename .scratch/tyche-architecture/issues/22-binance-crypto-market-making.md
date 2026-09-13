# Binance BTC 与 ETH 衍生品的做市及账户能力

Type: research
Labels: wayfinder:research
Status: resolved
Assignee: research-binance-crypto
Parent: ../map.md
Blocked by: none

## Question

用户已选择首版同时对 BTC、ETH 期权及永续合约做双边做市，当前一个账户暂按普通保证金考虑，实际账户模式待确认且需要配置。核实当前官方 API 和产品资料，区分加密期权买入、卖出已有多头与卖出开仓能力，做市资格、MMP/断线自动撤单及普通账户可用性；不能直接把商品期权规则外推到 BTC/ETH。

梳理所选衍生品的行情和订单接口、当前测试环境、账户/保证金及持仓模式的关系、必要的产品开通条件、共享限流边界，以及普通账户与组合保证金路径的区别。永续本位选择由正在进行的访谈决定；如尚未得到选择，只记录会影响选型的差异，不全面扩展所有衍生品。

输出有直接官方来源、日期/版本边界的中文研究资产，标明公开事实、工程推论与必须以实际账户验证的内容。不承诺任何实际账户具有卖出开仓权限，不访问账户或发订单。

## Comments

来源为 [Binance 首版产品与交易权限范围](12-binance-scope.md) 的已确认范围输入。用户要求的是双边做市，具体卖方开仓要求及永续本位正在进一步明确。

## Answer

2026-09-10，完成官方资料调查，详见 [Binance BTC/ETH 期权与 USDT 永续的做市及账户能力](../research/binance-crypto-market-making.md)。研究已按用户后续选择收敛到 USDT 本位永续、普通账户路径，并明确期权必须支持无多头卖出开仓。

- 现行官方公告和 FAQ 明确合格普通用户可对 BTC/ETH 期权卖出开仓，需要对应产品准入及 Options `Long & Short Sell` 模式；不能将商品期权限制或旧错误码笼统外推为“只有做市商能卖出开仓”。用户实际账户能力仍未验证。
- 期权卖出开仓、官方做市项目资格、MMP 和 Options 倒计时撤单分别记录。普通卖出开仓权限不能证明拥有做市商专用保护接口；Futures 倒计时撤单的权限与作用域也需单独核对。
- 普通 Options cross margin 不代表与 Futures/Margin 共用可用保证金。账户产品、保证金范围、Futures 持仓模式和 Options 卖出开仓模式是不同概念；组合保证金另有接入与准入路径。
- 官方当前确实将 Options demo 地址写为 `demo-fapi` / `demo-fstream`，但本次没有完成合约、路由或卖出开仓测试。不能自行构造替代测试地址，也不能用模拟验证代替生产权限证据。
- 当前一个账户下仍有按产品、UID、IP 等不同作用域定义的配额与设置。研究记录了 UM/CM 共享控制的事实，没有将未经证实的 EAPI 配额关系自行合并。

研究上下文：独立分支 `research/binance-crypto-market-making`，提交 `f04c7fde6316707155e88707823895a15ad696d8`；完整资产已复制回当前工作目录并通过 SHA256 一致性检查。未访问账户、切换模式或发送订单。
