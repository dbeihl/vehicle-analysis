# Reliability into cost

Date: 2026-08-10
Status: approved, not implemented

## Problem

Two of the three maintenance terms in `costPerMile` are identical for every vehicle:

| Term | Default | Varies per vehicle? |
| ---- | ------- | ------------------- |
| `scheduled_maint_per_mile` | $0.080/mi | No |
| `repairReserve()` | $0.0557/mi | No, only by odometer band |
| tires | varies | Yes, truck vs crossover |

A per-mile constant is a pure offset in a comparison. Both maintenance terms shift all 79 costs per mile by the same amount, so neither can change which vehicle wins — the README says as much in "Adjusting the assumptions". The tool therefore claims a Land Cruiser and a Grand Wagoneer cost the same to repair over 140,000 miles.

Meanwhile the dataset already carries a per-vehicle `reliability` score, and it feeds only the value axis. The judgment that a vehicle breaks more often exists in the data and is excluded from the one place it costs money.

## Decisions taken

Three forks were settled before design, and the alternatives are recorded because each has a real cost.

### 1. Reliability stays in the value score, with the meanings split

Reliability is 20% of the default value weighting. Once it also moves cost, one underlying judgment reaches the frontier through both axes.

**Taken:** cost absorbs the dollars; the slider is redefined as time in the shop rather than money. Downtime is a real cost the dollar figure does not capture, so the two are not the same quantity.

**Rejected:** removing reliability from the value score (breaks every six-weight preset and shared link), and cutting its default weight to offset (an arbitrary correction, invisible to anyone reading the chart).

Residual overlap is real and gets stated in the notes rather than engineered away.

### 2. The spread is anchored to published brand repair costs

RepairPal's 2026 brand averages: Toyota $441/yr, all-brand average $652, BMW $968, Land Rover $1,174. Worst-to-best ratio **2.66x**.

**Taken:** that ratio is the parameter's default, cited.

**Rejected:** a deliberately timid 0.85x–1.15x band (likely too small to move any frontier position, making the change decorative), and shipping the spread as a panel field with no defensible default (a default still has to be picked, and most people never open the panel).

### 3. The Cost axis is retagged where people read it

Cost is the only axis the README calls trustworthy: computed from the workbook. Reliability is one of the two it calls a SWAG. After this change the Cost axis carries a guess.

**Taken:** the Cost slider's provenance tag becomes `computed + judgment`, both hint texts say so, and the README says so in the axis-trust section and the "Before trusting any of it" list.

**Rejected:** README-only (the page is what people use), and a per-vehicle breakdown line in the detail panel (most transparent, but it adds a row to an already dense panel — revisit if the question comes up in use).

## Design

### The multiplier

One new input in `data/inputs.json`:

```json
"repair_cost_spread_ratio": 2.66
```

Applied at the call site in `costPerMile`, so `repairReserve`'s signature and the exported API are untouched:

```js
repairReserve(inp) * Math.pow(inp.repair_cost_spread_ratio, (50 - v.reliability) / 100)
```

Geometric around reliability 50, with the exponent divided by 100 rather than 50, so the parameter **is** the worst-to-best ratio across the full 0–100 scale. No second constant to keep in sync with the first.

At the shipped defaults:

| Reliability | Multiplier | Reserve $/mi |
| ----------- | ---------- | ------------ |
| 100.0 (best in fleet) | 0.613x | $0.0342 |
| 65.2 (fleet median) | 0.862x | $0.0480 |
| 50.0 (anchor) | 1.000x | $0.0557 |
| 17.4 (worst in fleet) | 1.376x | $0.0766 |

Applied spread across the real fleet is 2.24x, a gap of $0.043/mi, about **$2,337/yr** at 55,000 miles.

### Neutral is 1.0, not 0

`Math.pow(0, x)` returns 0 or Infinity and destroys the engine, so the off switch for a ratio is 1, not 0. This is worth stating because every other assumption in this model turns off at zero.

Multiplication by 1.0 is exact in IEEE-754, so at ratio 1.0 every cost per mile reproduces the pre-change value bit for bit. The oracle work below depends on that property, and a test asserts it directly rather than trusting it.

### The workbook oracle

`test_engine.mjs` checks the engine against 11 figures the spreadsheet computed independently, plus the balanced-six winner and the efficient frontier. The README calls this the only check not written by this codebase.

The spreadsheet has no reliability term. So `workbook_oracle` means "what the spreadsheet computed" and the ratio is neutralized to **1.0 across the entire oracle path**, not only the 11 published figures — the winner and frontier assertions are workbook-derived too and would otherwise have to be rewritten, which would destroy the check rather than update it.

`dump_variants` in `build.py` pairs each variant with the inputs it should be evaluated under, mirroring how `strip_for_oracle` already pairs a variant with its own prices.

`data/engine-fixture.json` is regenerated via `freeze_fixture.py` for the `full` variant, which the README already sanctions for a deliberate model change.

### Assumptions, stated rather than fixed

**Scheduled maintenance stays flat.** Oil, filters, and brakes are scheduled rather than failure-driven, so reliability is the wrong lever for them. Service-interval pricing does vary by brand; that is a separate change with its own source.

**The anchor is reliability 50, not the fleet median.** `costPerMile` sees one vehicle at a time, so anchoring to the fleet would make every vehicle's cost move whenever a row is added. The side effect: the fleet's median reliability is 65.2, not 50, so the fleet-average reserve falls about 14% below today's $0.0557. That is a level shift in the dollars, not a change in the ordering.

**The reliability score is still a SWAG.** This change makes a guess load-bearing on the axis that was previously the trustworthy one. Decision 3 exists because of that, and the README's standing recommendation — NHTSA complaint and TSB data, UK DVSA MOT results — is the path to replacing the guess with something measured.

**Recall counts were considered and rejected as the source.** `data/recalls.json` already caches NHTSA campaign counts for 71 of 79 nameplates, but only 42 carry full year coverage, and recall work is manufacturer-paid. A recall count measures defect propensity, not owner spend.

## Touch list

| File | Change |
| ---- | ------ |
| `data/inputs.json` | `repair_cost_spread_ratio: 2.66` |
| `engine.js` | multiplier at the `repairReserve` call site in `costPerMile` |
| `build.py` | `REQUIRED_ENGINE_FIELDS` += `reliability`; `dump_variants` pairs each variant with its inputs |
| `test_engine.mjs` | oracle path runs at ratio 1.0; new assertion that ratio 1.0 reproduces the pre-change figures exactly |
| `data/engine-fixture.json` | regenerated by `freeze_fixture.py` |
| `index.html` | `AXES` tag and both hint texts; notes fine print; `buildExport`'s fixed-assumption block, labelled `Repair cost spread, worst/best` |
| `test_export.mjs` | `Repair cost spread, worst/best` added to the required-label list |
| `README.md` | six-axes section and "Before trusting any of it" |

## How this gets verified

- `python3 test_build.py` green, including the 11 published workbook figures still matching at ratio 1.0
- The new bit-for-bit assertion: ratio 1.0 reproduces every pre-change cost per mile
- A ranking diff before and after, recorded in the PR, so the change in the frontier is visible rather than asserted
- `python3 build.py --check` clean

## Sources

- [RepairPal reliability ratings](https://repairpal.com/reliability) — brand average annual repair costs
- [Toyota](https://repairpal.com/reliability/toyota) $441/yr, [BMW](https://repairpal.com/reliability/bmw) $968/yr, [Land Rover](https://repairpal.com/reliability/land-rover) $1,174/yr
