# High-Mileage Vehicle Decision Model

**[dbeihl.github.io/vehicle-analysis](https://dbeihl.github.io/vehicle-analysis/)**

Cost-per-mile, durability, and comfort analysis for a driver covering **55,000 miles a year**, buying used at ~40,000 miles and selling around 180,000. Hamilton County, Indiana.

Seventy-nine vehicles plotted on two axes: cost, against a **value** score that combines the other five axes at whatever weights the sliders are set to. The ones on the efficient frontier are those nothing else beats on both at once, usually four to ten of the seventy-nine. Everything grey is dominated: something else is better on both counts, so you never need to consider it. Move the six weight sliders and the frontier redraws.

## What's here

| Path | What it is |
| ---- | ---------- |
| `data/vehicles.csv` | The dataset. One row per vehicle, observations and judgments only |
| `data/inputs.json` | Every cost assumption — fuel, tires, repair reserve, the depreciation curve |
| `engine.js` | The cost model. The only implementation; inlined into the page at build |
| `build.py` | Emits the dataset and inlines the engine into `index.html` |
| `test_build.py` | Checks the data pipeline, and shells out to Node to check `engine.js` |
| `test_engine.mjs` | Checks `engine.js` against the frozen Python fixture, the workbook's published figures, the balanced-six winner, and the efficient frontier, run by `test_build.py` under Node |
| `fetch_recalls.py` | Caches NHTSA recall-campaign counts into `data/recalls.json` |
| `index.html` | The interactive frontier explorer. Generated, but self-contained once built. Cost per mile is computed in the browser by `engine.js` |
| `vehicle-turnover-planner.xlsx` | The original spreadsheet model. 11 tabs, ~3,170 live formulas |

Open `index.html` in a browser to run it. The page itself has no dependencies; it needs a browser and nothing else.

The scripts need **Python 3.8 or newer**, standard library only, no pip install. Running `test_build.py` also needs **Node 20+** to check `engine.js`. Node is a development dependency; the published page never touches it.

```bash
python3 build.py        # regenerate index.html from data/
python3 test_build.py   # check the cost engine and the data's provenance rules
python3 build.py --check  # fail instead of rewriting; for CI or a pre-commit hook
```

## Modifying the data

Both tasks below end the same way: run `build.py`, then `test_build.py`. `build.py` refuses to write if a price carries an incomplete provenance record, so read this section before editing, or the build will reject the row. `python3 test_build.py` remains the single command that runs everything, including the `engine.js` checks. It shells out to Node itself, so there is nothing else to run by hand.

Both tasks also change what `data/engine-fixture.json` should say: it is a frozen snapshot of every vehicle's cost per mile at the prices that were in the CSV when it was captured. Changing any price, or adding a vehicle, requires regenerating it first, or `test_build.py` fails by comparing the new numbers against the old snapshot:

```bash
python3 freeze_fixture.py
```

### Adding a vehicle

One row in `data/vehicles.csv`. Never fill in cost per mile or the 0–100 axis scores — `build.py` computes those, and a stored copy would go stale.

```csv
name,category,tier,deprec_5yr,deprec_source,price,price_year,observed_price,observed_price_odometer,price_source,msrp,...
Toyota Land Cruiser,Full-size BOF SUV,1,0.42,estimated,58000,,,,,,...
```

Leave `price_year`, `observed_price`, `observed_price_odometer`, and `price_source` empty if you only have an estimate. An estimate with a blank provenance is honest; the tool labels it `placeholder`. An estimate wearing a year and a source is not, and the build rejects it.

### Correcting a price

Do not edit `price`. Add `observed_price` alongside it:

```diff
-Toyota Highlander Hybrid,...,36000,,,,,...
+Toyota Highlander Hybrid,...,36000,2023,39596,40000,"Edmunds/CarGurus, 879 listed 2023 examples",...
```

`price` stays at its original value on purpose. `test_build.py` strips `observed_price` and re-runs the engine against that original figure to confirm the *formula* still matches the spreadsheet's published numbers. Overwrite `price` and you destroy the only check that is independent of this codebase.

`observed_price` requires `price_year`, `price_source`, and `observed_price_odometer` (the odometer reading the price was observed at). Missing any of the three fails `build.py`, with the row named.

## Where prices come from

`build.py` uses a sourced observed market price where one exists, and the original placeholder everywhere else. Each vehicle is tagged with the basis it used.

Every monetary figure in this project is USD. As a data-entry check against a foreign-currency or decimal-point error, `build.py` rejects a price outside a plausible USD range, or more than double the highest in its own category.

| Column | Meaning |
| ------ | ------- |
| `observed_price` | A sourced market price for that model year. Preferred over everything. The aggregation varies and `price_source` records it: the Highlander Hybrid is an average across 879 listings, the Escalade a median across three services that disagreed by $5,000 |
| `price_year` | The model year being priced. The 40,000-mile buy point is a roughly 3-year-old vehicle, so in 2026 that is a 2023 |
| `price_source` | Which listing services, and how many listings |
| `price` | The original placeholder: no year, no trim, no source. Kept because `test_build.py` needs it to check the engine against the workbook |
| `msrp`, `msrp_year`, `msrp_trim`, `msrp_source` | Reference only. What the vehicle cost new |

**MSRP no longer computes a used price.** Deriving one through the retention curve was tried and retired: `resale_multiplier` is built from five-year depreciation while the buy point is a three-year-old vehicle, so fast-depreciating models were penalised twice. It put the 2023 Escalade at $50,941 against an observed $70,777 across three listing services, which is worse than the placeholder it replaced.

`build.py` refuses to run if a price carries an incomplete provenance record. An unflagged placeholder reads exactly like a verified figure once it reaches the page.

**4 of the 79 rows carry an observed price today.** Until that number is much higher, the ranking is biased toward whatever is still on a placeholder. A partially corrected dataset is more misleading than a uniformly wrong one: uniform error largely cancels in a ranking, and partial correction does not.

## Adjusting the assumptions

The eyebrow summary under the masthead is a button. Click it to open a panel where you can change eleven cost assumptions. The summary reads like `55,000 mi/yr · buy at 40k · sell at 180k · gas $3.55`, followed by a `change` prompt. When you edit any field, it appends `· edited` in teal so you can see at a glance that something differs from the defaults.

The eleven fields are split into two groups, and the split is not cosmetic. The first eight can change which vehicle ranks highest, because each one multiplies against something that varies per vehicle: the two odometers interact with each vehicle's depreciation curve, annual mileage divides against the cost of capital (`capital * years / miles` reduces to `capital / annual_miles`, and capital scales with each vehicle's price), fuel prices divide by its MPG, and the two tire prices and tire life depend on whether it wears truck or crossover tires.

The remaining three, labelled "Budget only", are maintenance per mile, insurance, and registration. Those are identical for every vehicle, so they shift all 79 costs per mile by the same constant. They change what the vehicle costs you; they cannot change which one wins.

The panel validates as you type. Numbers must fall within published ranges. The buy odometer cannot equal or exceed the sell odometer in either direction; if you try, the field rejects the input and marks itself invalid.

When you adjust the buy odometer, any observed price shifts with you. If a price was measured at a different mileage, the tool rescales it along that vehicle's own depreciation curve so the comparison stays honest. A price observed at a market listing is labelled `listed`. A price scaled to a different odometer is labelled `scaled`. An estimate carrying no source is labelled `estimate`.

Clicking Reset restores all eleven assumption fields to their defaults. It does not reset the weight sliders, the category filter, or your selection. The view encodes into the URL fragment: changed inputs, weights, filter, and selection all persist when you share a link. The eleven input fields are all-or-nothing: if any one of them is malformed or out of range, none of them apply and the page loads at defaults, so a truncated or edited link can never half-apply. An unrecognised weight, filter, or selection key is simply dropped and the rest of the fragment still applies.

## The six axes are not equally trustworthy

- **Cost** is computed from the workbook.
- **Efficiency** is EPA and observed MPG.
- **Comfort** starts from decibel-meter readings at 55 mph, then subtracts for documented seat complaints and body-on-frame ride harshness. Models tagged "estimated" had no published reading.
- **Longevity** uses odds of reaching 250,000 miles against each study's own baseline, but 45 of the 79 vehicles have no published figure.
- **Quality** and **Reliability** are informed guesses. Quality comes from drivetrain architecture, reliability from Consumer Reports brand record minus documented mid-life failure patterns. Neither is measured data, and both are labeled as such in the tool.

## Before trusting any of it

- **Most purchase prices are still placeholders, not quotes.** They are the biggest lever in the model. See "Where prices come from" above for which rows are verified.
- **Base trim understates what people buy.** Where a row carries an MSRP it is base trim unless `msrp_trim` says otherwise, and the 2026 Highlander Hybrid spans $48,815 to $56,470 across its three trims. Observed listing averages reflect the real trim mix and do not have this problem.
- **Not tax advice, and none of it is modelled in this repo.** The tax analysis lives only on the spreadsheet's `Tax` tab; `build.py` and the page ignore it entirely. W-2 employees cannot deduct business mileage: the Tax Cuts and Jobs Act (TCJA) suspended it and the One Big Beautiful Bill Act (OBBBA, 2025) made that permanent. Section 179 and bonus depreciation at a 30-month turnover cadence are a timing benefit rather than a saving, because Section 1245 recapture takes it back as ordinary income on sale. Talk to a CPA.
- **The depreciation curve is directional.** It comes from pooled asking-price cross-sections of ~327,000 listings, not the same VIN tracked over time.
- **Several figures expire.** Fuel prices, IRS mileage rates, and the iSeeCars baselines all move annually. The tax law moved twice during the period the analysis covers.

- **The spreadsheet is no longer authoritative.** `data/vehicles.csv` is. The spreadsheet still holds the `Sources` and `Tax` tabs, which have no equivalent in the repo, but its `Models` tab stopped tracking the CSV once prices were corrected. `test_build.py` still uses its published figures as an oracle, which works because it compares against the untouched `price` column.

Every material number is cited on the workbook's `Sources` tab, each with a note on how much weight it deserves.

## Attribution

Contains data from NHTSA and EPA (US Government works, public domain). Consumer Reports, J.D. Power, iSeeCars, and RepairPal figures are cited, not redistributed.
