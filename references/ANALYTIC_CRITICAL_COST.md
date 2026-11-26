# Analytic critical abstention cost c*

> Generator: `tools/analytic_critical_cost.py`. Data: `out_keystone_v43/results.json` (20 seeds per endpoint and strategy).
> This is algebra, not an empirical range: in the S1-S5 pipeline the classification threshold is fixed at 0.5 and cost enters scoring only,
> so `du/dc_abst = -(1-coverage)` holds exactly and the indifference point is available in closed form.

## 1. Results

| Endpoint | c* (median) | 95% interval | Fitted slope | Delta(1-coverage) | Identity gap | Min R2 | seeds |
|---|---|---|---|---|---|---|---|
| hERG | **0.2602** | [0.2449, 0.2777] | 0.8182 | 0.8180 | 0.0002 | 0.9999999905 | 20 |
| DILI | **0.5150** | [0.4353, 0.6352] | 0.8750 | 0.8750 | 0.0000 | 0.9999999938 | 20 |
| BBB_Martins | **0.2091** | [0.1938, 0.2793] | 0.6478 | 0.6480 | 0.0002 | 0.9999999707 | 20 |

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

## 4. Relation to the earlier interval statement

The earlier phrasing "the boundary lies between 0.2 and 0.5" merged two critical values from three endpoints into one range.
This table separates them into three comparable scalars (0.209 / 0.260 / 0.515) with individual intervals.
The interval was therefore not a resolution limit but a conflation of three different c* values.
