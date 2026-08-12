# NHTSA complaint evidence into the repair multiplier

Date: 2026-08-12
Status: approved, not implemented

## Problem

Since the reliability multiplier shipped, `reliability` sets each vehicle's repair reserve. That column is the weakest-sourced field in `data/vehicles.csv`: every other judgment carries a source (`deprec_5yr`/`deprec_source`, `longevity`/`longevity_source`, `price`/`price_source`), and `reliability` carries none. No script in the repo computes it.

Its values are a brand ranking with small per-model deductions. The bands barely overlap — Toyota spans 85.0–100.0, Ford 50.7–72.7, Jeep 17.4–42.4 — so Toyota's worst row outranks Ford's best, and twelve vehicles sit pinned at exactly 100.0. The cost model therefore says a Toyota's repair reserve is 0.61x and a Jeep's 1.38x largely because of the badge.

NHTSA publishes consumer complaints for free with no API key. This spec introduces per-model evidence where today there is a brand prior.

## What the data actually supports

Measured across 66 of 79 nameplates, model years 2019/2021/2023 (the sampling `fetch_recalls.py` already uses).

**Raw complaint counts are unusable.** They scale with fleet size, and NHTSA publishes no sales or registration denominator. The highest counts in this fleet are the RAV4, CR-V, Pilot, Outback and Forester — the best-selling crossovers in the US, all scored highly. The lowest are the Grand Wagoneer, Canyon and Navigator, all low-volume and scored poorly. Ranking on counts ranks sales.

**Severity share works.** For each vehicle, the fraction of its own complaints naming an expensive subsystem — engine, power train, electrical, fuel, suspension, steering, service brakes. Being a ratio, fleet size cancels exactly.

| Correlation against `reliability` | Value |
| --------------------------------- | ----- |
| Raw | -0.61 |
| With vehicle category removed | -0.54 |

Both figures are computed over the 59 nameplates carrying at least 40 complaints, so a vehicle with four complaints does not get a vote in the correlation. That threshold exists only for measuring the relationship; the design below uses no threshold, because shrinkage already gives a four-complaint vehicle almost no weight.

The category effect is real but small: full-size body-on-frame SUVs average a 78% severe share against 55% for mid-size crossovers. Removing it costs only 0.07 of correlation, so severity share is not merely detecting trucks. A subjective score built from brand reputation is corroborated at -0.54 by data it was never derived from.

**Where they disagree, the evidence compresses the prior's extremes.** Toyota's trucks are not exceptional on expensive-component complaints (Tundra and Tacoma sit mid-pack while scored 100.0), and the American vehicles are less catastrophic than scored (Ram 1500 at 2,116 complaints, Explorer at 796). Some of the raw gap is scale shape — the prior clusters at 100 while severity share spreads smoothly — so ordering agreement (-0.54) is the honest measure, not value differences.

## Design

### The empirical score

```
empirical(v) = 100 * (ANCHOR_HIGH - severity_share(v)) / (ANCHOR_HIGH - ANCHOR_LOW)
```

clamped to 0–100, with **`ANCHOR_LOW = 0.20`** and **`ANCHOR_HIGH = 0.95`**.

The anchors are fixed, not the fleet's own min and max. A fleet-relative rescale would make every vehicle's cost move when a row is added — the same trap avoided by anchoring the spread multiplier at reliability 50 rather than the fleet median. The observed range is 0.219 (Toyota Venza) to 0.944 (Cadillac Escalade ESV), so these anchors bracket it with only slight headroom; a future vehicle outside them clamps rather than rescaling its peers.

### The blend

```
weight(v)   = n(v) / (n(v) + k)
effective(v) = weight(v) * empirical(v) + (1 - weight(v)) * reliability(v)
```

`n` is the vehicle's total complaint count across the sampled years. **`k = 100`**, a new input `complaint_evidence_k`, meaning a vehicle needs 100 complaints before the evidence outvotes the prior.

Shrinkage rather than a fixed weight, because a fixed weight gives a vehicle with 4 complaints the same authority as one with 2,116. At `k = 100`: Ram 1500 (2,116) lands at 95% evidence, Nissan Titan (45) at 31%, and a vehicle with no data at 0% — it keeps the prior with no special case in the code.

**Neutral is `k = 0`**, which yields weight 0 for every vehicle and reproduces today's behavior exactly. Unlike the spread ratio, whose neutral is 1, this parameter turns off at zero. That difference is a trap and is called out in both the code comment and the README.

`effective` replaces `reliability` **only** in `repairMultiplier`. The `reliability` axis score, its slider, and the value calculation are untouched: severity share measures what breaks expensively, the slider measures time in the shop, and merging them would rebuild the double-count deliberately split when the multiplier shipped. It would also invalidate every six-weight preset and shared link.

### Data and provenance

`fetch_complaints.py` mirrors `fetch_recalls.py` — same `split_name`, same `YEARS`, same "a 400 is not a zero" discipline — and caches to `data/complaints.json`. NHTSA's gateway answers **200 with `{"message": "Endpoint request timed out"}` and no `results` key** on large queries; that is a failure wearing a success code and must be retried, not recorded as zero complaints. The Ford F-150 is unreachable this way without generous timeouts.

Three columns join `data/vehicles.csv` beside `reliability`, giving it the provenance every other judgment column already has:

| Column | Meaning |
| ------ | ------- |
| `complaint_severity_share` | Fraction of this vehicle's complaints naming an expensive subsystem |
| `complaint_n` | Total complaints across the sampled model years |
| `complaint_years` | Which model years NHTSA actually answered for |

`build.py` rejects a row carrying any one of the three without the others, matching how it already rejects an `observed_price` without its year, source, and odometer.

### Coverage is two-tier, and the page says so

Thirteen nameplates have no complaint data and another thirteen fall below `k`. Those ride mostly or entirely on the prior.

This is the failure mode the README already names for prices: "A partially corrected dataset is more misleading than a uniformly wrong one." The mitigation is the one the repo already uses — the `listed` / `scaled` / `estimate` badges. The detail panel gains a badge on the reliability figure:

| Badge | Condition |
| ----- | --------- |
| `evidence` | weight >= 0.5 (53 vehicles today) |
| `mixed` | 0 < weight < 0.5 (13 today) |
| `judgment` | no complaint data (13 today) |

**The residual risk, stated rather than solved.** The uncovered vehicles are not a random sample: they are hybrids and 2024+ models with little complaint history, which skew toward the reliable end. So vehicles keeping a generous prior are disproportionately ones already scored well, while older trucks are pulled toward mediocrity by evidence. Badging makes this visible; it does not remove it. Revisit once hybrid complaint histories mature.

## What this does not do

- **Volume is not used.** Only the composition of complaints. Any future use of counts needs a sales denominator, which NHTSA does not publish.
- **Scheduled maintenance stays flat.** Unchanged from the previous spec: scheduled work is scheduled, not failure-driven.
- **The category effect is not modelled.** Body-on-frame SUVs really do show a higher severe share, but that is a body-style term, not a reliability term, and belongs in its own change if it is ever wanted.
- **Recall campaign counts are not used.** `data/recalls.json` correlates -0.36 with the prior but is volume-confounded through regulatory scrutiny and variant count — the heaviest campaign loads belong to the F-150, Ram 1500 and Explorer, three of the highest-volume vehicles sold.

## How this gets verified

- The workbook oracle keeps passing untouched: it already runs at a neutral spread ratio, and `k = 0` is additionally neutral, so the 11 published figures, the balanced-six winner, and the frontier are unaffected by construction
- A test that `k = 0` reproduces every pre-change cost per mile exactly, the same bit-for-bit check the spread ratio shipped with
- A test that a vehicle with no complaint data lands at exactly its prior, and one with a large `n` lands within a point of its empirical score
- A test that severity share of 0.20 and 0.95 map to 100 and 0, and that values outside the anchors clamp rather than exceeding the scale
- `build.py` rejects a partial complaint record, proven by a rejecting case
- A recorded before/after ranking diff in the PR, on the `full` variant at the shipped weights

## Sources

- [NHTSA complaints API](https://www.nhtsa.gov/nhtsa-datasets-and-apis) — free, no API key, US government work in the public domain
- Correlations and coverage figures computed from a full pull of all 79 nameplates on 2026-08-12; the numbers in this spec are measured, not estimated
