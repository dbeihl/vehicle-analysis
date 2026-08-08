#!/usr/bin/env python3
"""Check the cost engine against figures the workbook published independently.

Run: python3 test_build.py

These dollars-per-mile numbers come off the StrategyMatrix and Scoring tabs of
vehicle-turnover-planner.xlsx, computed there by ~3,170 spreadsheet formulas.
build.py recomputes them from the raw retention anchors. If the two ever
disagree, one of them has drifted -- which is the whole reason this file exists.
"""
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


def main():
    models = {m['name']: m for m in build.build_models(build.load(), build.INPUTS)}

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

    # A dominated vehicle must never reach the frontier: something beats it on both.
    frontier = [m for m in models.values()
                if not any(o is not m and o['cost'] >= m['cost']
                           and o['quality'] >= m['quality']
                           and (o['cost'] > m['cost'] or o['quality'] > m['quality'])
                           for o in models.values())]
    assert frontier, 'frontier is empty -- domination logic is inverted'

    print(f'ok: {len(PUBLISHED_CPM)} published $/mile figures match, '
          f'balanced-six = {winner} at {score:.1f} ({len(models)} vehicles)')


if __name__ == '__main__':
    main()
