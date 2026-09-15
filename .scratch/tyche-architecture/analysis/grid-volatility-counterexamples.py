"""Reproduce algebraic counterexamples for Q64, not a UMM integration test.

Run: python .scratch/tyche-architecture/analysis/grid-volatility-counterexamples.py
Inputs represent finite, currently valid curve values at the Grid calculation seam.
"""

from math import erf, isclose, isfinite, sqrt


EPSILON = 1e-6


def grid_slice(base_vol, quote_vol, inventory_shift, auto_shift, risk_enabled):
    assert all(isfinite(x) for x in
               (base_vol, quote_vol, inventory_shift, auto_shift))
    intermediate = quote_vol - inventory_shift
    # MyMath.h LessEqual(intermediate, 0): intermediate < DOUBLE_TICK.
    accepted = not (intermediate < EPSILON)
    # Counterfactual downstream value if this gate permits execution.
    pricing_vol = base_vol + auto_shift
    if risk_enabled:
        pricing_vol += quote_vol - base_vol
    return intermediate, accepted, pricing_vol


cases = [
    ("rejects_valid_pricing_vol", (0.20, 0.20, 0.30, 0.0, True), False, 0.20),
    ("accepts_invalid_pricing_vol", (0.20, 0.05, 0.0, -0.10, True), True, -0.05),
    ("inventory_shift_001", (0.20, 0.20, 0.01, 0.0, True), True, 0.20),
    ("inventory_shift_002", (0.20, 0.20, 0.02, 0.0, True), True, 0.20),
]

for name, inputs, expected_acceptance, expected_vol in cases:
    gate_vol, accepted, pricing_vol = grid_slice(*inputs)
    assert accepted == expected_acceptance
    assert isclose(pricing_vol, expected_vol, abs_tol=1e-12)
    print(f"{name}: gate_vol={gate_vol:.6f}, "
          f"accepted={accepted}, downstream_vol={pricing_vol:.6f}")

assert grid_slice(0.20, EPSILON, 0.0, 0.0, False)[1]
assert not grid_slice(0.20, EPSILON / 2, 0.0, 0.0, False)[1]

# Independent exact-normal-CDF reference, not UMM's approximate phi function:
# S=K=100, T=1, r=q=0, vol=0.20 -> positive finite ATM call value.
normal_cdf = lambda x: 0.5 * (1.0 + erf(x / sqrt(2.0)))
call_price = 100.0 * (2.0 * normal_cdf(0.20 / 2.0) - 1.0)
assert 0.0 < call_price < 100.0
print(f"reference_call_at_vol_020={call_price:.9f}")
print("All algebraic counterexamples and tolerance checks passed.")
