# Per-trim rows

Date: 2026-08-09
Status: approved, not implemented

## Problem

David: *"I think we are underestimating the cost of vehicles. Yes, the BASE price is 39 or 46k, but no one buys those. Usually it's 5-10k more per trim model you get."*

He is right, and the step size varies more than a flat assumption would allow:

| Vehicle | Base | Next trim | Step |
| ------- | ---- | --------- | ---- |
| Toyota Highlander Hybrid | XLE $48,815 | Limited $53,270 | +$4,455 |
| Lincoln Navigator | $94,590 | Reserve $104,590 | +$10,000 |
| Lexus LX 700h | $115,735 | loaded $141,500 | +$25,765 |

So $5-10k holds for luxury and understates the top end, while mainstream Toyota steps run nearer $4,500. A single multiplier would be wrong in both directions, which is the argument for real per-trim data.

**Where the underestimate actually lives.** The four rows carrying an `observed_price` are averages across hundreds of real listings, so they already embed the market's trim mix. The other 75 are base-ish estimates with no provenance. Those are the ones too low.

## The structure is three dimensions, and two already exist

Rows today are effectively **nameplate x powertrain**: `Toyota Highlander (gas)` and `Toyota Highlander Hybrid` are separate rows, as are `Chevrolet Tahoe` and `Chevrolet Tahoe 3.0L Duramax`. Trim is a third, orthogonal dimension.

This matters for efficiency. EPA publishes MPG per **drivetrain configuration, not per marketing trim** — all three Highlander Hybrid AWD trims return one EPA record at 35 hwy, and the Escalade's two records are engine choices rather than trim levels. Efficiency therefore belongs to the powertrain dimension, which is already handled. The only trim effect on MPG is wheel size, which EPA does not expose.

## Design

### 1. Row identity

The row key becomes `(nameplate, trim)`.

Every one of these is a `name -> value` map today and collides the moment a nameplate repeats:

- `data/engine-fixture.json`
- `data/recalls.json`
- `PUBLISHED_CPM`, `EXPECTED_WINNER`, `EXPECTED_FRONTIER` in `test_engine.mjs`

The migration lands as its own change, before any trim data is added, so the key change and the data change are separately reviewable. `data/engine-fixture.json` is regenerated deliberately at that point and the diff inspected — the first regeneration since #18 closed, and the reason #18 had to close first.

`data/recalls.json` stays keyed by nameplate. Recalls are issued against a nameplate and model year, not a trim, so replicating them per trim would invent precision that does not exist. The build joins them on the nameplate portion of the key.

### 2. Schema

Three new columns in `data/vehicles.csv`:

| Column | Meaning |
| ------ | ------- |
| `trim` | One of `base`, `volume`, `loaded`. The tier, used for comparison and filtering |
| `trim_name` | The real badge: XLE, Limited, Reserve, Platinum |
| `mix_price` | On the four rows that have one: the listing-average price. **Recorded, never used as a price** |
| `wheel_in` | Wheel diameter in inches for that trim. Published and objective |
| `avg_mpg` | Real-world observed MPG from EPA's user-submitted data |
| `avg_mpg_n` | How many submissions back `avg_mpg`. **Required whenever `avg_mpg` is present** |

`trim` is the machine-comparable tier; `trim_name` is what a reader recognises. Both are required.

### 3. Three tiers, not every published trim

Every vehicle gets `base`, `volume`, and `loaded`. Roughly 237 rows, against 400-plus if every published badge became a row.

The reason is comparability. A consistent tier lets a reader hold trim constant and compare loaded against loaded, which is the comparison worth making. With every published badge there is no way to say which tier a trim belongs to, and the frontier fills with cross-tier comparisons — a base Escalade beating a loaded Highlander — that describe nothing anyone shops.

`volume` means the trim that actually sells, not the arithmetic middle of the ladder.

### 4. What varies by trim

**Varies:** price, comfort, GVWR, wheel diameter.

**Copies down from the nameplate:** category, tier, `deprec_5yr`, quality, longevity, reliability, transmission, engine, risk, 250k odds, efficiency.

Those are properties of the vehicle rather than of its equipment level. A Platinum Highlander has the same drivetrain architecture and the same odds of reaching 250,000 miles as an XLE.

**GVWR is the one with money attached.** Some nameplates cross 6,000 lb between trims, which flips Section 179 eligibility. For a self-employed buyer that is a tax consequence riding on a wheel-and-tire package, and it is invisible in a nameplate-level dataset. The existing `heavy` boolean and `gvwr_note` become per-trim.

### 4a. Wheel size and real-world MPG

Wheel diameter is recorded per trim. It is published, objective, and it is the physical driver behind two things: the ride component of comfort, where the effect is large and well understood, and the fuel-economy difference between an XLE on 18s and a Platinum on 22s.

Real-world MPG is recorded from EPA's user-submitted data alongside the EPA rating, in `avg_mpg`, **with its sample size in `avg_mpg_n`**.

The sample size is not optional, because the data is thin. Sampling eight nameplates: three resolved and all three had fewer than ten submissions. The Highlander Hybrid's average rests on a single submission, and the CR-V's single submission reads 27.8 against an EPA 32 — a 4.2 mpg gap that is one person's driving, not a measurement.

So `avg_mpg` is displayed and used only above a documented threshold, and below it the row falls back to the EPA figure and says so. This is the same discipline already applied to `comparable` on recall counts and `years_answered` on the recall cache: record the number, record what stands behind it, and let the threshold decide whether it speaks.

Fuelly was evaluated and rejected as a source: it returns HTTP 403 to automated requests, so there is no legitimate programmatic path to it.

**Efficiency itself remains a powertrain property.** EPA publishes one rating per drivetrain configuration, verified across six nameplates — the RAV4 Hybrid, Highlander, and CR-V each return a single record covering their entire trim ladder, and every multi-record case (Explorer, Tahoe, Grand Cherokee) splits on engine rather than trim. Trim genuinely affects real-world economy through mass and rolling resistance; nothing free measures it at that resolution, and the model does not guess.

### 5. Prices are sourced per tier

Every row carries its own sourced price. The four existing mix averages are **not** promoted to a tier; they move to `mix_price` and serve as a consistency check instead.

That check is free and worth having: for a nameplate with a known mix average, `base < mix < loaded` must hold. If it does not, the tier sourcing is wrong on a row backed by hundreds of listings. It is the only independent validation available on any price in the dataset.

`observed_price_odometer` continues to apply per row, so a tier price sourced at a different mileage still scales correctly.

### 6. Comfort becomes per-trim, closing #20

The page's own methodology says the decibel figures are the **"median across measured trims"**. The resolution existed upstream and was collapsed. Per-trim rows recover it rather than inventing it.

Alongside the recovered dB figures, comfort gains what #20 identified as missing and what trim actually drives: seat quality and adjustability, acoustic glass, and adaptive or air suspension. This is the concrete mechanism behind the observation that started this — a loaded Escalade feels wildly nicer than a Highlander while a decibel meter cannot see why.

Issue #20 is therefore done as part of this work, not after it. Doing it separately would mean touching every comfort figure twice.

### 7. The chart collapses by nameplate, closing #12

A nameplate renders as one point until selected, then expands to its trims. Without this, 237 near-identical points cluster into unreadable blobs, and the default frontier is full of cross-tier comparisons.

Tap targets are 11-13px today and would overlap badly at 237, which matters more once #17's phone check happens.

### 8. Currency, before any data entry

Every monetary figure in this project is USD, and #24's plausibility gate ships **before** the sourcing work, not after.

This is not hypothetical. While sourcing the 90k tier, a search returned "2026 Honda CR-V Hybrid starts at $60,585" from a Quebec dealer — CAD, roughly a 35% overstatement, caught only because it looked wrong beside its siblings. Sourcing ~700 numbers multiplies that exposure.

## Out of scope

- Every published badge rather than three tiers
- A modelled per-trim MPG derate. The effect is real but unmeasured at that resolution, and inventing a coefficient would undo the work of retiring the MSRP derivation
- Per-trim recall data, which NHTSA does not issue
- Model-year x odometer expansion (#10), which is a separate dimension

## Sequencing

1. #24 currency and plausibility gate
2. Row-key migration, including the first deliberate fixture regeneration
3. Chart collapse-by-nameplate (#12)
4. Schema columns and the three-tier structure, populated for the realistic contenders
5. Per-trim comfort (#20)
6. Remaining nameplates

Steps 1 through 3 change no vehicle data and can be verified against the existing figures. Only step 4 begins moving numbers.

## Testing

- Row-key uniqueness: no two rows share `(nameplate, trim)`, asserted at build
- Every row has both `trim` and `trim_name`, enforced in `price_problems()` alongside the existing provenance rules
- Tier ordering: within a nameplate, `base <= volume <= loaded` on price
- Mix-price bracket: where `mix_price` exists, `base < mix_price < loaded`
- Plausibility: every price within a documented USD range, per #24
- `avg_mpg` never appears without `avg_mpg_n`, and is never consumed below the threshold
- Wheel diameter present on every row, since it feeds the comfort ride sub-score
- Recall join: every trim row resolves to its nameplate's recall entry, and a nameplate absent from `recalls.json` degrades without failing
- The 158-comparison engine parity gate continues to pass after regeneration, against the new keys

## Risks

**Sourcing is the whole risk.** Roughly 700 figures across 237 rows, from a search surface that has already produced a CAD price and a hybrid quoted below its gas sibling. Populating contenders first (step 4) bounds the damage: the ~15 vehicles that can plausibly win get real scrutiny, and the rest stay single-row until someone needs them.

**The fixture regeneration is a one-way door.** After it, ground truth is whatever the JS engine produced rather than the frozen Python. #18's independence check now guards the property that made this dangerous, and the regeneration should still be diffed by hand rather than accepted silently.
