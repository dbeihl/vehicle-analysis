# High-Mileage Vehicle Decision Model

**[dbeihl.github.io/vehicle-analysis](https://dbeihl.github.io/vehicle-analysis/)**

Cost-per-mile, durability, and comfort analysis for a driver covering **55,000 miles a year**, buying used at ~40,000 miles and selling around 180,000. Hamilton County, Indiana.

Seventy-nine vehicles plotted on two axes. The ones on the efficient frontier are those nothing else beats on both cost and value at once, usually four to ten of the seventy-nine. Everything grey is dominated: something else is better on both counts, so you never need to consider it. Move the six weight sliders and the frontier redraws.

## What's here

| Path | What it is |
| ---- | ---------- |
| `data/vehicles.csv` | The dataset. One row per vehicle, observations and judgments only |
| `data/inputs.json` | Every cost assumption — fuel, tires, repair reserve, the depreciation curve |
| `build.py` | Computes cost per mile and the scoring axes, writes them into `index.html` |
| `test_build.py` | Checks the cost engine against figures the workbook published independently |
| `fetch_recalls.py` | Caches NHTSA recall-campaign counts into `data/recalls.json` |
| `index.html` | The interactive frontier explorer. Generated, but self-contained once built |
| `vehicle-turnover-planner.xlsx` | The original cost engine. 11 tabs, ~3,170 live formulas |

Open `index.html` in a browser to run it. Nothing to install; the page has no dependencies.

To change the data, edit `data/vehicles.csv` or `data/inputs.json`, then:

```bash
python3 build.py        # regenerate index.html
python3 test_build.py   # confirm the cost engine still agrees with the workbook
```

`build.py --check` fails instead of rewriting, for use in CI or a pre-commit hook.

Derived values (cost per mile, the 0–100 cost and efficiency axes) are never stored in the CSV. Adding a vehicle means adding a row.

## Where prices come from

`build.py` uses an observed market listing where one exists, and the original placeholder everywhere else. Each vehicle is tagged with the basis it used.

| Column | Meaning |
| ------ | ------- |
| `observed_price` | Average of real listings for that model year. Preferred over everything |
| `price_year` | The model year being priced. The 40,000-mile buy point is a roughly 3-year-old vehicle, so in 2026 that is a 2023 |
| `price_source` | Which listing services, and how many listings |
| `price` | The original placeholder: no year, no trim, no source. Kept because `test_build.py` needs it to check the engine against the workbook |
| `msrp`, `msrp_year`, `msrp_trim`, `msrp_source` | Reference only. What the vehicle cost new |

**MSRP no longer computes a used price.** Deriving one through the retention curve was tried and retired: `resale_multiplier` is built from five-year depreciation while the buy point is a three-year-old vehicle, so fast-depreciating models were penalised twice. It put the 2023 Escalade at $50,941 against an observed $70,777 across three listing services, which is worse than the placeholder it replaced.

`build.py` refuses to run if a price carries an incomplete provenance record. An unflagged placeholder reads exactly like a verified figure once it reaches the page.

**Four of seventy-nine rows are on observed prices today.** Until that number is much higher, the ranking is biased toward whatever is still on a placeholder. A partially corrected dataset is more misleading than a uniformly wrong one: uniform error largely cancels in a ranking, and partial correction does not.

## The six axes are not equally trustworthy

- **Cost** is computed from the workbook.
- **Efficiency** is EPA and observed MPG.
- **Comfort** starts from decibel-meter readings at 55 mph, then subtracts for documented seat complaints and body-on-frame ride harshness. Models tagged "estimated" had no published reading.
- **Longevity** uses odds of reaching 250,000 miles against each study's own baseline, but 42 of the 79 vehicles have no published figure.
- **Quality** and **Reliability** are informed guesses. Quality comes from drivetrain architecture, reliability from Consumer Reports brand record minus documented mid-life failure patterns. Neither is measured data, and both are labeled as such in the tool.

## Before trusting any of it

- **Most purchase prices are still placeholders, not quotes.** They are the biggest lever in the model. See "Where prices come from" above for which rows are verified.
- **Base trim understates what people buy.** Where a row carries an MSRP it is base trim unless `msrp_trim` says otherwise, and the 2026 Highlander Hybrid spans $48,815 to $56,470 across its three trims. Observed listing averages reflect the real trim mix and do not have this problem.
- **Not tax advice.** W-2 employees cannot deduct business mileage: TCJA suspended it and OBBBA made that permanent. Section 179 and bonus depreciation at a 30-month turnover cadence are a timing benefit rather than a saving, because Section 1245 recapture takes it back as ordinary income on sale. Talk to a CPA.
- **The depreciation curve is directional.** It comes from pooled asking-price cross-sections of ~327,000 listings, not the same VIN tracked over time.
- **Several figures expire.** Fuel prices, IRS mileage rates, and the iSeeCars baselines all move annually. The tax law moved twice during the period the analysis covers.

- **The workbook is no longer authoritative.** `data/vehicles.csv` is. The workbook still holds the `Sources` and `Tax` tabs, which have no equivalent in the repo, but its `Models` tab has not tracked the CSV since prices were corrected.

Every material number is cited on the workbook's `Sources` tab, each with a note on how much weight it deserves.

## Attribution

Contains data from NHTSA and EPA (US Government works, public domain). Consumer Reports, J.D. Power, iSeeCars, and RepairPal figures are cited, not redistributed.
