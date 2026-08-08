# High-Mileage Vehicle Decision Model

**[dbeihl.github.io/vehicle-analysis](https://dbeihl.github.io/vehicle-analysis/)**

Cost-per-mile, durability, and comfort analysis for a driver covering **55,000 miles a year**, buying used at ~40,000 miles and selling around 180,000. Hamilton County, Indiana.

Seventy-six vehicles plotted on two axes. The ones on the efficient frontier are those nothing else beats on both cost and value at once, usually six to ten of the seventy-six. Everything grey is dominated: something else is better on both counts, so you never need to consider it. Move the six weight sliders and the frontier redraws.

## What's here

| Path | What it is |
| ---- | ---------- |
| `index.html` | The interactive frontier explorer. Self-contained: no dependencies, no build step |
| `vehicle-turnover-planner.xlsx` | The cost engine. 11 tabs, ~3,170 live formulas |

Open `index.html` in a browser to run it locally. There is nothing to install.

## The six axes are not equally trustworthy

- **Cost** is computed from the workbook.
- **Efficiency** is EPA and observed MPG.
- **Comfort** starts from decibel-meter readings at 55 mph, then subtracts for documented seat complaints and body-on-frame ride harshness. Models tagged "estimated" had no published reading.
- **Longevity** uses odds of reaching 250,000 miles against each study's own baseline, but 42 of the 76 vehicles have no published figure.
- **Quality** and **Reliability** are informed guesses. Quality comes from drivetrain architecture, reliability from Consumer Reports brand record minus documented mid-life failure patterns. Neither is measured data, and both are labeled as such in the tool.

## Before trusting any of it

- **The purchase prices in the workbook are placeholders, not quotes.** They are the biggest lever in the model. Replace them with real local listings at your target odometer.
- **Not tax advice.** W-2 employees cannot deduct business mileage: TCJA suspended it and OBBBA made that permanent. Section 179 and bonus depreciation at a 30-month turnover cadence are a timing benefit rather than a saving, because Section 1245 recapture takes it back as ordinary income on sale. Talk to a CPA.
- **The depreciation curve is directional.** It comes from pooled asking-price cross-sections of ~327,000 listings, not the same VIN tracked over time.
- **Several figures expire.** Fuel prices, IRS mileage rates, and the iSeeCars baselines all move annually. The tax law moved twice during the period the analysis covers.

Every material number is cited on the workbook's `Sources` tab, each with a note on how much weight it deserves.

## Attribution

Contains data from NHTSA and EPA (US Government works, public domain). Consumer Reports, J.D. Power, iSeeCars, and RepairPal figures are cited, not redistributed.
