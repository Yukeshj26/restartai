# RestartAI Synthetic Production Recovery Benchmark

> [!NOTE]
> **SYNTHETIC BENCHMARK**: All results below are generated from 35 seeded synthetic manufacturing failure incidents for reproducible algorithmic comparison. They demonstrate the mathematical advantage of multi-supplier exposure optimization over naive procurement heuristics under simulated operational parameters.

---

## 1. Executive Summary

In emergency industrial breakdowns, factory procurement typically resorts to one of two naive heuristics:
1. **Cheapest-First (Procurement Default)**: Buy from the lowest-priced supplier first, ignoring transit delay.
2. **Fastest-Single (Panic Default)**: Pay whatever express surcharge is necessary to have a single vendor deliver the entire order in one shipment.

**RestartAI** implements a third approach: **Deterministic Multi-Supplier Economic Exposure Optimization**. It simultaneously evaluates 1-leg, 2-leg, and 3-leg splits to minimize total financial exposure:
$$\text{Total Economic Exposure} = \sum_{\text{legs}} (Q_i \times P_i) + \left( \max_{\text{legs}} t_i + t_{\text{install}} \right) \times \text{Downtime Rate}$$

---

## 2. Seeded Benchmark Methodology (35 Synthetic Incidents)

- **Seed**: `42` (strictly deterministic and reproducible).
- **Incident Sample**: 35 synthetic breakdown incidents across 7 critical machinery categories (CNC Production Lines, Injection Molding Units, Stamping Presses, Packaging Conveyors, Cold Headers, Automated SMT Pick-and-Place, and Extrusion Lines).
- **Failure Parameters**:
  - Downtime Loss Rates: ₹2,000/hr to ₹12,000/hr.
  - Quota Needed: 15 to 40 units.
  - Emergency Recovery Deadlines: 2.0 to 6.0 hours.
  - Sourcing Pool: 4–5 realistic suppliers per incident (standard bulk distributors, expedited hotshot vans, immediate counter stockists, and rapid motorbike freight).

---

## 3. Comparative Benchmark Results

| Performance Metric | Strategy 1: Cheapest-First | Strategy 2: Fastest-Single | Strategy 3: RestartAI (Adaptive Split) |
| :--- | :---: | :---: | :---: |
| **On-Time Recovery Rate** | **0.0%** (0/35) | **60.0%** (21/35) | **80.0%** (28/35) |
| **Deadline Breaches** | 35 breaches (100%) | 14 breaches (40%) | **7 breaches (20%)** |
| **Average Recovery Time** | 22.60 hours | 4.53 hours | **2.34 hours** |
| **Average Purchase Outlay** | **₹4,108.15** | ₹6,220.09 | ₹5,164.56 |
| **Average Total Economic Exposure** | ₹144,158.91 | ₹34,047.06 | **₹19,467.25** |
| **Average Savings vs Baseline** | Baseline | ₹110,111.85 (76.4%) | **₹124,691.66 (86.5%)** |

### Key Takeaways
1. **Cheapest-First Fails Catastrophically**: While Cheapest-First achieves the lowest raw parts purchase cost (saving ~₹1,056 per order), it causes catastrophic 18h–26h plant shutdowns, resulting in an average economic exposure of ₹144,158.91 (a 640% cost penalty compared to RestartAI) and 0% on-time recovery.
2. **Fastest-Single Overpays and Encounters Stockouts**: Fastest-Single avoids massive shutdowns when a vendor has 100% stock, but fails whenever no single vendor can supply the full quota in one vehicle (leading to 14 deadline breaches and ₹34,047 average exposure).
3. **RestartAI Wins on Total Exposure and Reliability**: By securing partial stock immediately from local counter stockists while simultaneously dispatching express freight for the remainder, RestartAI achieves an **80.0% on-time recovery rate** and reduces average economic exposure to **₹19,467.25** (saving ₹14,580 vs Fastest-Single and ₹124,692 vs Cheapest-First).

---

## 4. Counterfactual Explainer: The Golden Scenario

To understand why conventional procurement rules fail in real factories, consider the Golden Scenario (`CNC Production Line 4`, `SKF 6205-2RS`, Quantity 20, Downtime Loss ₹5,000/hr, Max Deadline 3.0h):

```
+---------------------------------------------------------------------------------------+
| COUNTERFACTUAL COMPARISON: GOLDEN SCENARIO                                             |
+---------------------------------------------------------------------------------------+
| Strategy 1: Cheapest-First (Supplier A)                                               |
| - Purchase Cost:  20 units x Rs 150/u  = Rs 3,000.00 (SAVED Rs 720 on parts!)        |
| - Arrival Time:   24.0h arrival + 0.5h install = 24.5h downtime                       |
| - Downtime Loss:  24.5h x Rs 5,000/hr   = Rs 122,500.00                               |
| - Total Exposure: Rs 3,000 + Rs 122,500 = Rs 125,500.00 (DEADLINE BREACHED BY 21.5h)  |
| - Net Penalty vs RestartAI: +Rs 111,780 (+815% LOSS)                                  |
+---------------------------------------------------------------------------------------+
| Strategy 2: Fastest-Single (Supplier B Alone)                                         |
| - Purchase Cost:  20 units x Rs 220/u  = Rs 4,400.00 (Expedited Courier Premium)      |
| - Arrival Time:   2.0h arrival + 0.5h install = 2.5h downtime                         |
| - Downtime Loss:  2.5h x Rs 5,000/hr   = Rs 12,500.00                                 |
| - Total Exposure: Rs 4,400 + Rs 12,500 = Rs 16,900.00 (Rs 14,400 arrival baseline)    |
| - Net Penalty vs RestartAI: +Rs 3,180 (+23% LOSS)                                     |
+---------------------------------------------------------------------------------------+
| Strategy 3: RestartAI (Supplier C 8u + Supplier D 12u Split)                          |
| - Purchase Cost:  (8 x Rs 180) + (12 x Rs 190) = Rs 3,720.00                          |
| - Arrival Time:   max(0.5h, 1.5h) + 0.5h install = 2.0h downtime                      |
| - Downtime Loss:  2.0h x Rs 5,000/hr   = Rs 10,000.00                                 |
| - Total Exposure: Rs 3,720 + Rs 10,000 = Rs 13,720.00 (FEASIBLE · OPTIMAL)           |
| - Net Savings:    Rs 111,780 saved vs Cheapest | Rs 3,180 saved vs Fastest-Single    |
+---------------------------------------------------------------------------------------+
```

---

## 5. API Endpoints

- `GET /api/benchmark/summary`: Returns the aggregate performance KPIs across all 35 synthetic incidents.
- `GET /api/recovery/{run_id}/counterfactual`: Generates the exact counterfactual comparison for any active recovery run.
