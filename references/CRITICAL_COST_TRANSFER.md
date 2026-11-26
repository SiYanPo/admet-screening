# Critical cost on two endpoints outside the preregistered set (transferability demonstration)

> Generator: `tools/analytic_critical_cost.py`. Data: `out_keystone_transfer/results.json` (20 seeds per endpoint and strategy).
> This is algebra, not an empirical range: in the S1-S5 pipeline the classification threshold is fixed at 0.5 and cost enters scoring only,
> so `du/dc_abst = -(1-coverage)` holds exactly and the indifference point is available in closed form.

> **Status**: transferability demonstration. These endpoints are outside the preregistered primary set; they test whether the estimator can be applied to endpoints the study was not designed around, and are not part of the primary hypothesis tests.

## 1. Results

| Endpoint | c* (median) | 95% interval | Fitted slope | Delta(1-coverage) | Identity gap | Min R2 | seeds |
|---|---|---|---|---|---|---|---|
| Ames | **0.7939** | [0.7740, 0.8245] | 0.7351 | 0.7350 | 0.0001 | 0.9999999862 | 20 |
| CYP3A4_Veith | **0.9019** | [0.8820, 0.9173] | 0.8471 | 0.8475 | 0.0004 | 0.9999999855 | 20 |

## 2. Closed form

```
c* = Delta_u(0) / (cov_S1 - cov_S4)
```

Equivalently `c* = Delta_u(0) / [ (1-cov_S4) - (1-cov_S1) ]`.

## 3. Three mandatory declarations

1. **Source of linearity**: the S1-S5 cost sweep is a post-hoc re-pricing (see the LEGACY / C18 note on `run_keystone.py::pick_threshold`);
   cost does **not** modify decided_mask. Hence c* is a critical price *under a fixed decision rule*, not a mechanism finding about decisions changing with cost.
2. **Slope equals the abstention-rate difference**: the measured slope deviates from `-(1-coverage)` by at most 0.0002. This is a self-consistency check, not independent evidence.
3. **Applicability**: under a cost-sensitive threshold (`adt.cost_decision.pi_cost_sensitive`, the S6 branch) decided_mask changes with cost, linearity breaks,
   and c* is no longer available in closed form. This table does not apply to that setting.
