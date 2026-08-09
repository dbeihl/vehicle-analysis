#!/usr/bin/env python3
"""Check the cost engine against figures the workbook published independently.

Run: python3 test_build.py

These dollars-per-mile numbers come off the StrategyMatrix and Scoring tabs of
vehicle-turnover-planner.xlsx, computed there by ~3,170 spreadsheet formulas.
build.py recomputes them from the raw retention anchors. If the two ever
disagree, one of them has drifted -- which is the whole reason this file exists.
"""
import pathlib

import build

# name -> $/mile, as published on StrategyMatrix (col L) and Scoring (col D).
PUBLISHED_CPM = {
    'Honda HR-V': 0.426,
    'Ford Escape Hybrid': 0.441,
    'Toyota Venza': 0.457,
    'Nissan Rogue': 0.459,
    'Ford Maverick Hybrid': 0.460,
    'Toyota Highlander Hybrid': 0.517,
    'Honda Ridgeline': 0.519,
    'Toyota Grand Highlander Hybrid': 0.580,
    'Chevrolet Tahoe': 0.674,
    'Chevrolet Tahoe 3.0L Duramax': 0.703,
    'Toyota Sequoia (pre-2023 5.7 V8)': 0.717,
}

# StrategyMatrix "Balanced six": winner and score.
BALANCED = {'cost': 25, 'quality': 15, 'longevity': 15,
            'efficiency': 10, 'reliability': 20, 'comfort': 15}
EXPECTED_WINNER, EXPECTED_SCORE = 'Toyota Highlander Hybrid', 89.9

# The four the page reports undominated at those weights. Everything else is
# beaten on both cost and value by something on this list.
EXPECTED_FRONTIER = {'Toyota Highlander Hybrid', 'Toyota Venza',
                     'Ford Escape Hybrid', 'Honda HR-V'}


def main():
    # Validate the ENGINE against the workbook, not the data. The workbook was
    # built on the original placeholder prices, so rows since repriced from a
    # verified MSRP will legitimately disagree. Stripping msrp here keeps this
    # check meaningful: it fails on formula drift, not on intentional data edits.
    rows = [dict(r, msrp='', observed_price='') for r in build.load()]
    models = {m['name']: m for m in build.build_models(rows, build.INPUTS)}

    for name, expected in PUBLISHED_CPM.items():
        assert name in models, f'{name} missing from data/vehicles.csv'
        got = models[name]['cpm']
        assert abs(got - expected) < 0.001, \
            f'{name}: workbook says {expected}/mi, build.py computes {got}/mi'

    ranked = sorted(
        ((sum(w * models[n][k] for k, w in BALANCED.items()) / 100, n)
         for n in models), reverse=True)
    score, winner = ranked[0]
    assert winner == EXPECTED_WINNER, \
        f'balanced-six winner is {winner}, workbook says {EXPECTED_WINNER}'
    assert abs(score - EXPECTED_SCORE) < 0.05, \
        f'balanced-six score {score:.1f}, workbook says {EXPECTED_SCORE}'

    # Reproduce the frontier the page draws: cost against the weighted value of
    # the other five axes. Asserting the frontier is merely non-empty proves
    # nothing -- the cheapest vehicle is undominated by construction.
    value_axes = {k: w for k, w in BALANCED.items() if k != 'cost'}
    total = sum(value_axes.values())
    for m in models.values():
        m['value'] = sum(w * m[k] for k, w in value_axes.items()) / total

    frontier = {m['name'] for m in models.values()
                if not any(o is not m and o['cost'] >= m['cost']
                           and o['value'] >= m['value']
                           and (o['cost'] > m['cost'] or o['value'] > m['value'])
                           for o in models.values())}
    assert frontier == EXPECTED_FRONTIER, \
        f'frontier changed: {sorted(frontier)} != {sorted(EXPECTED_FRONTIER)}'

    # Price provenance, checked against the real rows rather than the stripped
    # ones. A price with no recorded year, source, or trim is indistinguishable
    # from a verified one by the time it reaches the page.
    real = build.load()
    problems = build.price_problems(real)
    assert not problems, 'price provenance incomplete:\n  ' + '\n  '.join(problems)

    check_price_resolution()
    check_readme_counts(real)

    observed = sum(1 for r in real if r.get('observed_price'))
    print(f'ok: {len(PUBLISHED_CPM)} published $/mile figures match, '
          f'balanced-six = {winner} at {score:.1f}, '
          f'{observed} observed / {len(real) - observed} placeholder '
          f'({len(models)} vehicles)')


def check_price_resolution():
    """Exercise buy_price against constructed rows.

    Asserting only that the basis is one of two literals buy_price can return
    is tautological -- it passes no matter what the function does. These cases
    pin the actual precedence and the resolved amount.
    """
    inp = build.INPUTS
    base = dict(deprec_5yr=0.4, price=30000)

    amount, basis = build.buy_price(dict(base, observed_price='31500', msrp='50000'), inp)
    assert (amount, basis) == (31500.0, 'observed'), \
        f'observed must win over msrp, got {amount} via {basis}'

    amount, basis = build.buy_price(dict(base, observed_price='', msrp='50000'), inp)
    assert (amount, basis) == (30000.0, 'placeholder'), \
        f'msrp must not derive a price -- it double-penalised at the 3-year ' \
        f'buy point and was retired. Got {amount} via {basis}'

    amount, basis = build.buy_price(dict(base), inp)
    assert (amount, basis) == (30000.0, 'placeholder')

    # Every provenance combination the gate is supposed to reject.
    rejected = [
        dict(name='a', observed_price='1', price_source='x'),           # no year
        dict(name='b', observed_price='1', price_year='2023'),          # no source
        dict(name='c', price_year='2023'),                              # orphaned year
        dict(name='d', price_source='x'),                               # orphaned source
        dict(name='e', msrp='1', msrp_year='2026', msrp_source='x'),    # no trim
        dict(name='f', msrp='1', msrp_trim='XLE', msrp_source='x'),     # no year
    ]
    for row in rejected:
        assert build.price_problems([row]), f'gate accepted a bad row: {row}'
    assert not build.price_problems(
        [dict(name='ok', observed_price='1', price_year='2023', price_source='x')])


def check_readme_counts(rows):
    """Stop README statistics drifting from the data they describe."""
    readme = (pathlib.Path(__file__).parent / 'README.md').read_text()
    no_study = sum(1 for r in rows if 'no study data' in (r['longevity_source'] or ''))
    assert f'{no_study} of the {len(rows)} vehicles have no published figure' in readme, \
        (f'README longevity count is stale: data says {no_study} of {len(rows)}')
    observed = sum(1 for r in rows if r.get('observed_price'))
    assert str(observed) in readme, f'README does not mention the {observed} observed rows'


if __name__ == '__main__':
    main()
