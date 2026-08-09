# Live inputs and shareable state

Date: 2026-08-08
Status: approved, not implemented

## Problem

The workbook lets a user change any assumption and watch the whole model
recalculate. The web tool cannot. Its six sliders reweight the scoring axes but
cannot touch the cost model, because cost per mile is computed by `build.py` at
build time and baked into `index.html` as a fixed `cpm` per vehicle.

So the page answers exactly one question: what is the best vehicle for a driver
covering 55,000 miles a year, buying at 40,000 and selling at 180,000, paying
$3.55 for gas in Hamilton County, Indiana. Anyone whose situation differs has no
way to say so.

## What the measurement says

Perturbing each input one at a time across all 79 vehicles: **no single input
change flips the winner.** The reason is structural rather than a property of
this dataset.

Inputs divide into two kinds:

- **Rank-changing** inputs multiply against a per-vehicle attribute. Gas price
  divides by each vehicle's MPG; the odometer points interact with each
  vehicle's depreciation curve; tire cost depends on truck versus crossover
  class; sales tax and the capital rate scale with price.
- **Rank-neutral** inputs are identical for every vehicle — maintenance per
  mile, the repair reserve, insurance, registration. These add the same constant
  to all 79 cost-per-mile figures, so they move the budget and can never move
  the choice.

The panel should present these separately. A user who doubles the repair reserve
and sees the ranking unchanged has learned something real, but only if the
interface told them which kind of input they were touching.

## Design

### 1. The cost engine moves to the browser

`build.py` stops computing cost. It emits raw vehicle rows plus the contents of
`data/inputs.json` into the page. A single `costPerMile(vehicle, inputs)`
function in JS becomes the only implementation, called at the head of the
existing `compute()`.

Everything downstream already derives from there — the 0–100 cost axis, the
frontier, the ranking, the detail card, so the render path does not change.

The Python `cost_per_mile`, `retention_index`, and `repair_reserve` are deleted.

### 2. Verification survives the deletion

Deleting the Python engine removes what `test_build.py` currently runs, but not
what it checks against. The oracle is the workbook's 11 independently computed
dollars-per-mile figures, which are data, not code.

`test_build.py` will shell out to Node, run the JS engine over all 79 vehicles
at default inputs, and assert:

- each of the 11 published $/mile figures, to within 0.001
- the balanced-six winner and score (Toyota Highlander Hybrid, 89.9)
- the four-vehicle frontier set

Node is a development dependency only. The published page keeps zero runtime
dependencies, which is the property that lets it work as a single static file.

If Node is unavailable the test must fail loudly rather than skip. A skipped
check reads exactly like a passing one.

### 3. Prices carry their own anchor

Every `observed_price` is currently a price at 40,000 miles, and nothing records
that. Moving the buy odometer to 70,000 would leave a 40,000-mile price against
a 70,000-mile buy point — an $11,740 error on the Highlander Hybrid alone.

Add a per-row `observed_price_odometer`, set to 40,000 for the four existing
rows. Price then resolves as:

```
price(buy_odo) = observed_price * R(buy_odo) / R(observed_price_odometer)
```

where `R` is the existing retention-curve interpolation.

This is not the MSRP derivation that was retired. That one applied a
five-year `resale_multiplier` at a three-year buy point and penalised
fast-depreciating models twice. This scales along a single vehicle's own curve,
starting from a measured price, with no multiplier involved. A future listing
sourced at 72,000 miles needs no special handling, and the global buy odometer
becomes free to move.

`price_problems()` gains a rule: `observed_price` requires
`observed_price_odometer`. Same fail-closed posture as the existing provenance
checks.

### 4. The panel

Eleven inputs, collapsed by default so the page opens exactly as it does today.

| Changes the answer | Changes only the budget |
| ------------------ | ----------------------- |
| Annual miles | Maintenance $/mi |
| Buy odometer | Insurance $/yr |
| Sell odometer | Registration $/yr |
| Gas $/gal | Repair reserve (single multiplier over the three bands) |
| Diesel $/gal | |
| Tire cost ($/set) | |
| Tire life (miles) | |

Requirements:

- A reset-to-defaults control.
- A visible marker whenever any input differs from default. Without it, someone
  screenshots a customised chart and it reads as the canonical answer.
- Inputs validate at the boundary. A blank, negative, or non-numeric value must
  not reach the cost function — `annual_miles` of 0 divides by zero, and a
  negative odometer produces a nonsense retention index. Reject and hold the
  last good value rather than rendering NaN.
- Sell odometer must exceed buy odometer. Enforced, not assumed.

### 5. Price provenance in the display

The detail card gains a provenance marker with three states: observed,
placeholder, and derived. The last is shown whenever the buy odometer has moved
away from a price's own anchor, so a scaled price never looks like a measured
one.

This subsumes issue #11, which should be closed by this work rather than built
separately.

### 6. Shareable state

The full view encodes into the URL fragment: changed inputs, axis weights,
active filter, and selected vehicle. Only values differing from default are
encoded, so an untouched page keeps a clean URL.

The fragment is used rather than a query string: it is never sent to the server,
and this tool is shared by sending someone a link and having them send one back.

On load, an invalid or partial fragment falls back to defaults rather than
failing. A shared link that half-works is worse than one that cleanly does not.

## Out of scope

- The remaining ~20 workbook inputs (financing mode, loan APR, down payment,
  individual repair-reserve bands, the depreciation anchor table)
- Preset scenarios
- `localStorage` persistence. The URL covers sharing, which is the actual need

## Testing

- Node-based oracle test as described in section 2, replacing the current
  Python engine check
- Price anchoring: a vehicle whose `observed_price_odometer` differs from
  `buy_odometer` resolves to the scaled figure, exactly at its anchor and
  correctly away from it
- `price_problems()` rejects `observed_price` without `observed_price_odometer`
- Input validation rejects zero, negative, blank, and non-numeric values, and
  rejects a sell odometer below the buy odometer
- URL round-trip: encode a modified state, reload from the fragment, and get an
  identical rendering. Malformed fragments fall back to defaults
- Rank-neutrality holds: changing only budget-group inputs leaves the ranking
  identical. This is the claim the panel's layout asserts, so it should be
  checked rather than assumed

## Risks

**The engine port is the whole cost model.** Depreciation, resale, fuel, tires,
maintenance, repair reserve, insurance, registration, sales tax, and cost of
capital. A silent arithmetic difference between the Python that produced the
current page and the JS that replaces it would change every number without
changing anything visible. The Node oracle test is the control, and it should be
written before the Python engine is deleted, not after.

**Scaled prices are still estimates.** Section 3 is sounder than the derivation
it replaces, but it remains a model. Away from 40,000 miles the numbers are
interpolations from one measured point, and section 5 exists so that is visible.
