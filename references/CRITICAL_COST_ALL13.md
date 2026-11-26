# Critical abstention cost c*

> Generator: `adt cstar`. Data: `out_keystone_all13\results.json` (20 seeds per endpoint and strategy).  Comparator: `S1_naive_majority`.
> This is algebra, not an empirical range: in the S1-S5 pipeline the classification threshold is fixed at 0.5 and cost enters scoring only,
> so `du/dc_abst = -(1-coverage)` holds exactly and the indifference point is available in closed form.

> **Status**: transferability demonstration. These endpoints are outside the preregistered primary set; they test whether the estimator can be applied to endpoints the study was not designed around, and are not part of the primary hypothesis tests.

## 1. Results

| Endpoint | c* (median) | 95% interval | Fitted slope | Delta(1-coverage) | Identity gap | Min R2 | seeds |
|---|---|---|---|---|---|---|---|
| BBB_Martins | **0.2091** | [0.1938, 0.2793] | 0.6478 | 0.6480 | 0.0002 | 0.9999999707 | 20 |
| hERG | **0.2602** | [0.2449, 0.2777] | 0.8182 | 0.8180 | 0.0002 | 0.9999999905 | 20 |
| DILI | **0.5150** | [0.4353, 0.6352] | 0.8750 | 0.8750 | 0.0000 | 0.9999999938 | 20 |
| Ames | **0.7939** | [0.7740, 0.8245] | 0.7351 | 0.7350 | 0.0001 | 0.9999999862 | 20 |
| CYP3A4_Veith | **0.9019** | [0.8820, 0.9173] | 0.8471 | 0.8475 | 0.0004 | 0.9999999855 | 20 |
| HIA_Hou | **0.2200** | [0.1841, 0.2400] | 0.6411 | 0.6410 | 0.0001 | 0.9999999798 | 20 |
| Bioavailability_MA | **-0.2813** | [-0.4374, 0.0953] | 0.4922 | 0.4920 | 0.0002 | 0.9999999738 | 20 |
| PGP_Broccatelli | **0.8001** | [0.6407, 0.9297] | 0.5306 | 0.5310 | 0.0004 | 0.9999999687 | 20 |
| CYP3A4_Substrate_CarbonMangels | **1.1958** | [1.0639, 1.3230] | 0.7185 | 0.7190 | 0.0005 | 0.9999999844 | 20 |
| CYP2C9_Substrate_CarbonMangels | **1.3496** | [1.3083, 1.3560] | 0.9852 | 0.9850 | 0.0002 | 0.9999999941 | 20 |
| CYP2D6_Substrate_CarbonMangels | **1.2090** | [1.1333, 1.2437] | 0.9000 | 0.9000 | 0.0000 | 0.9999999906 | 20 |
| CYP2C9_Veith | **0.9244** | [0.9190, 0.9564] | 0.8586 | 0.8590 | 0.0004 | 0.9999999966 | 3 |
| CYP2D6_Veith | **0.6424** | [0.6332, 0.6465] | 0.9665 | 0.9660 | 0.0005 | 0.9999999927 | 3 |

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
