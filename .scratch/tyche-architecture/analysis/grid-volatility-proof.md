# Grid 库存波动率项与拒绝条件的数学核查

日期：2026-09-14。对应[期权定价、曲面拟合与参数状态](../issues/14-option-pricing-model.md)的 Q64。

## 结论与证明范围

能证明：在下述正常输入域，`distance*N/PTh` 的直接波动率定价作用被覆盖；现有中间值门槛既不是最终 BS 波动率为正的必要条件，也不是其充分条件。初次证明时保留了独立库存限制的可能解释；用户随后明确该项用于“改变库存报价”，故覆盖该定价作用不符合本次选定规范。不能据此简单删除它。本次不判断整个 Grid 策略、最终订单或交易收益的正确性，不修改 UMM。

判定“正确”须先给出规范：若规范是将该库存项加入定价，当前代码不满足；若规范是检查最终定价波动率，当前门槛单独不满足；若规范是限制库存，当前门槛可写为一种库存约束，其是否符合所需业务规则仍待用户确定。

## 源码依据

路径均相对 `D:/dev/UMM/`：

| 位置 | 事实 |
| --- | --- |
| `MS_COM/CommAMM5/source/strategy/QuoteAlgo_Grid.h:175–190` | 读取报价曲面，扣库存项，检查中间值，写入 theoVol。 |
| 同文件 `:75–91` | theoVol 被重新设为基础曲面波动率，再叠自动 IV 项和按开关启用的曲面风险差。 |
| 同文件 `:94–121` | Delta 风险另调基价，BS 定价后再加价格单位 optionLean；theo4QC 使用独立基础定价。 |
| `MS_SHR/utility/MyMath.h:19,65–67` | DOUBLE_TICK 为 1e-6，LessEqual(x,0) 实际比较 x<1e-6。 |
| `MS_COM/CommAMM5/source/strategy/QuoteCommon.cpp:3879–4013` | 两个 AutoLean 函数不读取临时 theoVol 或 distance/PTh，覆盖前的值未通过它们间接保留。 |
| `MS_COM/CommAMM5/source/common/CalcResult.h:89,112` | 无参 GetValue 返回当前值；GetValueAndLast 可回退到历史值。 |
| `MS_COM/CommAMM5/source/strategy/QuoteCommon.cpp:164–171` | 刷新报价曲面后却返回基础曲面有效位。 |
| `MS_SHR/tradingTool/BlackScholesModelCommodity.cpp:28–34` | 对非正标的、行权价、期限或 sigma 返回全零 Greeks，而不是显式失败对象。 |

## 假设、符号与实际公式

先限定两条当前曲面均有效且有限、所用价格等定价输入有效、PTh 非零、无并发修改、无持仓整数加法溢出。这里的波动率均为小数单位，0.20 表示 20%。

- C：基础曲面波动率。
- Q：报价风险曲面波动率，正常域内两个读取点取得相同当前值。
- N：该行权价 call.netPosition + put.netPosition。
- D：distance；H：PTh；h = D*N/H。
- a：autoIVLeanCoef * autoLean。
- b：曲面风险偏移开关，取 0 或 1。
- epsilon = 1e-6。

旧门槛检查 g = Q - h；仅当 g >= epsilon 时允许继续通过这一道门槛。

实际送入后续 BS 的波动率为：

\[
\sigma = C + a + b(Q-C).
\]

门槛拒绝时，此公式表达“若仅越过此门槛，后续会使用什么值”，不表示被拒绝轮次实际执行了 BS。最终价格还受独立基价调整、optionLean、edge、舍入和风控影响。

## 命题一：库存项的直接定价作用消失

CalcGridVol 中写入的 Q-h 在主流程中无条件被 C 覆盖。两个 AutoLean 函数没有读取该临时结果，因此不存在这两条调用中的间接传递。后续只有 a 和 b(Q-C) 加入 sigma。

在 C、Q、a、b 固定且门槛通过时，改变 h 不改变 sigma。即局部函数关系满足 d(sigma)/dh=0。它只可能通过此门槛改变本轮能否继续。

这不意味着策略不响应持仓：Q、Delta 基价偏移和 optionLean 均可能依赖持仓。不能由该局部导数推出完整策略价格对 N 的总导数为零，也不能推出最终成交相同。

## 命题二：门槛不是最终波动率为正的必要或充分条件

取 b=1，则 sigma=Q+a，且 sigma-g=a+h。源码未建立 a 与 h 之间使两门槛等价的约束。

| 反例 | C | Q | h | a | g | 门槛 | sigma |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 拒绝可用的定价波动率 | 0.20 | 0.20 | 0.30 | 0 | -0.10 | 拒绝 | 0.20 |
| 放过无效的定价波动率 | 0.20 | 0.05 | 0 | -0.10 | 0.05 | 通过 | -0.05 |

第一行中 sigma>0 但 g<epsilon，因此门槛不是必要条件。第二行中 g>=epsilon 但 sigma<0，因此门槛不是充分条件。各值远离容差边缘，不依赖浮点舍入细节。

第一行可取 S=K=100、T=1、r=q=0，并固定其他价格偏移为0。数学 BS 参考看涨价为 100*[2*Phi(0.1)-1]，约为 7.965567455，有限且为正。这说明被此门槛拒绝不等于 BS 在该输入上不能定价，不代表此轮一定通过后续风险检查。

第二行也不等于证明一定报出负价格：UMM 的 BS 对 sigma<=0 返回全零 Greeks，随后还存在 optionLean 和其他检查。本证明只说明这道前置门槛无法保障 BS 波动率输入有效。

这些是计算接口上的有限值反例。未加载生产配置或回放数据，未证明特定账户当前状态必然可达。若另有全局约束能排除它们，应提供该约束并纳入证明；现有配置读取和所核查函数没有证明这种约束。

## 命题三：它可以表达另一种库存约束，但不自动证明业务正确

当 D>0、H>0，门槛可等价写成：

\[
N \leq \frac{H(Q-\epsilon)}{D}.
\]

它是一种依赖报价曲面波动率的单侧净持仓上限，不是双侧绝对持仓上限。以此作为独立策略规则时，门槛拒绝一个数学上可定价的状态并不矛盾：风险规则本来可以拒绝可定价状态。

但代码或 BS 公式本身不能证明这个单侧上限就是用户需要的库存目标；用户随后选择了改变库存报价，而非仅作为独立库存上限。D=0 时门槛退化为 Q>=epsilon；D/H<0 时不等号方向反转。

## 根据用户明确的目的确定的新公式（Q65–Q66 已接受）

用户已接受直接将库存项作为策略私有波动率偏移，仅施加一次：

\[
\sigma_{new}=C+a+b(Q-C)-\frac{D}{H}N.
\]

这保留当前实际生效的其他波动率项。不能只删除覆盖赋值而无视风险开关和后续风险差，否则可能把 Q-C 重复施加。共享基础曲面仍不写入该库存项，风险报价曲面 Q 也不预先包含本项再在最终公式重复扣减。

固定其他定价输入和偏移，令 k=D/H>0。在 sigma_new>0、S/K/T 等输入有效的域内，源码 BS vega = exp(-qT)*S*phi(d1)*sqrt(T)>0，所以这个独立库存项对 BS 理论价的边际作用是：

\[
\left.\frac{\partial P_{BS}}{\partial N}\right|_{\text{其他项固定}}=-k\,\mathrm{Vega}<0.
\]

即净多仓增加时该项压低理论价，净空仓增加时抬高理论价；对 call 和 put 都成立。D=0 时该项无作用，D<0 会反转方向，H=0 无定义，所以已确定允许 D>=0 且要求 H>0，并校验有限性。最终实际定价波动率失效时停止相关合约新单并尝试撤单，不钳位或自动关闭该项；具体允许范围数值待定。

这是该项的局部方向性证明，不是多种风险偏移全部随 N 改变后的总导数证明，更不保证经过 edge、舍入、VolBand 与风控后的实际挂单必然连续单调变化，也不证明最优性或盈利性。

## 异常值域与验证边界

上述两反例不依赖 NaN、Inf 或回退值。异常域另有问题：GetValueAndLast 与 GetValue 可取得不同版本；LessEqual 对 NaN 不会触发拒绝；PTh 的读取未见非零正值校验。因此不能把正常域公式提升为对所有机器状态的安全性证明。

未编译 UMM、未执行全链路回放、未修改或替换算法。附带的[数值脚本](grid-volatility-counterexamples.py)独立复现该计算片段，检查两个逻辑反例、两组通过门槛但不同 h 得到相同 sigma 的样本，以及 epsilon 边界；BS 示例使用标准正态 CDF，不是 UMM 的近似 phi 实现。

复现命令：`python .scratch/tyche-architecture/analysis/grid-volatility-counterexamples.py`。本次全部断言通过，参考看涨价为 7.965567455。

## 本次读取的文件 SHA-256

用于识别证明所依据的源码版本，不代表审计整个仓库：

- QuoteAlgo_Grid.h：`5FCFA03C9F1EA2C0003D16A2C8EAABD1E79F59927BAAD4EF84AD9DD9B60CB1FE`
- QuoteCommon.cpp：`56A0913064BAF202BE64AD5BAF5F57D8CF4BD7ECBC7D23C310163F4F393E8ED2`
- CalcResult.h：`21C45A00E2E8216C85B0E63DCDB13216D646A49D6221490E45DE1ABE20D78264`
- MyMath.h：`BA1E81872EE53F91BBB605A317C96A531261F275AD34E26112EBE6519A828F9D`
- BlackScholesModelCommodity.cpp：`92E1B0758691E8A4CAC3E079457E10DFFF7B47261F370FEDF1CB79D7D2FBABD3`
