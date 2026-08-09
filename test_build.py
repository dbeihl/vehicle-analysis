#!/usr/bin/env python3
"""Check build.py's data pipeline and, via Node, the JS cost engine against
figures the workbook published independently.

Run: python3 test_build.py

The dollars-per-mile numbers come off the StrategyMatrix and Scoring tabs of
vehicle-turnover-planner.xlsx, computed there by ~3,170 spreadsheet formulas.
engine.js is the only cost engine now -- check_js_engine_parity() shells out
to Node, which checks the workbook's published figures, the balanced-six
winner, and the efficient frontier against VA.costPerMile (see
test_engine.mjs). If the two ever disagree, one of them has drifted -- which
is the whole reason this check exists.
"""
import pathlib
import re

import build


def main():
    # Price provenance, checked against the real rows. A price with no
    # recorded year, source, or trim is indistinguishable from a verified
    # one by the time it reaches the page.
    real = build.load()
    problems = build.price_problems(real)
    assert not problems, 'price provenance incomplete:\n  ' + '\n  '.join(problems)

    check_price_resolution()
    check_emitted_schema(real)
    check_js_engine_parity(real)
    check_recall_status_classification()
    check_readme_counts(real)

    observed = sum(1 for r in real if r.get('observed_price'))
    print(f'ok: {observed} observed / {len(real) - observed} placeholder '
          f'({len(real)} vehicles)')


def check_emitted_schema(rows):
    """Every field the JS engine reads must reach the page.

    Python raises KeyError on a missing field. JS computes undefined * 2 = NaN
    and renders a broken chart with no error, so absence has to be caught here.
    """
    models = build.build_models(rows, build.INPUTS)
    for m in models:
        missing = [f for f in build.REQUIRED_ENGINE_FIELDS if f not in m]
        assert not missing, f'{m["name"]}: emitted row lacks {missing}'
        assert isinstance(m['deprec5yr'], float), \
            f'{m["name"]}: deprec5yr must be numeric, got {m["deprec5yr"]!r}'
        assert m['tireClass'] in ('Truck', 'Crossover'), \
            f'{m["name"]}: unexpected tireClass {m["tireClass"]!r}'
        if m['observedPrice'] is not None:
            assert m['observedAt'], \
                f'{m["name"]}: observedPrice without observedAt anchor'
        # cost, peryr, and cpm are computed in the browser now (VA.costPerMile
        # at the head of compute()). A baked-in value here would mean Python
        # silently started shipping stale cost figures again, defeating the
        # point of moving the computation to INPUTS + engine.js.
        baked_in = [f for f in ('cpm', 'peryr', 'cost') if f in m]
        assert not baked_in, \
            f'{m["name"]}: cost fields must be computed client-side, not emitted: {baked_in}'


def check_js_engine_parity(rows):
    """Run engine.js under Node against the frozen Python output.

    The 11 workbook figures prove the formula; this proves the port. Both are
    needed -- the workbook covers 11 of 79 vehicles at one input set.

    A missing Node must fail rather than skip. A skipped check reads exactly
    like a passing one.

    Dumps two model arrays, not one. build_models() resolves buy_price into
    the emitted 'price' field, so a vehicle with an observed price loses its
    raw placeholder there -- nulling observedPrice on that dict client-side
    cannot recover it. The workbook_oracle variant needs rows stripped of
    observed_price *before* build_models runs, same as main()'s workbook
    comparison, so its 'price' field is the true placeholder.
    """
    import json
    import shutil
    import subprocess

    node = shutil.which('node')
    assert node, ('node is required to test the cost engine and was not found. '
                  'It is a development dependency only; the page ships without it.')

    root = pathlib.Path(__file__).parent
    stripped = [dict(r, msrp='', observed_price='') for r in rows]
    dumped = {
        'full': build.build_models(rows, build.INPUTS),
        'workbook_oracle': build.build_models(stripped, build.INPUTS),
    }
    # build_models() is 1:1 per row, so a short dump means something upstream
    # silently dropped vehicles. Without this, an empty dump still exits 0 --
    # node has nothing to iterate and prints "ok: 0 comparisons" -- which is
    # exactly the "assertion that could never fail" shape this file exists to
    # avoid elsewhere.
    assert len(dumped['full']) == len(rows), \
        f"full: dumped {len(dumped['full'])} models, expected {len(rows)}"
    assert len(dumped['workbook_oracle']) == len(rows), \
        f"workbook_oracle: dumped {len(dumped['workbook_oracle'])} models, expected {len(rows)}"
    dump = root / 'build-models.json'
    dump.write_text(json.dumps(dumped))
    try:
        r = subprocess.run([node, str(root / 'test_engine.mjs')],
                           cwd=root, capture_output=True, text=True)
    finally:
        dump.unlink(missing_ok=True)
    assert r.returncode == 0, f'JS engine parity failed:\n{r.stdout}{r.stderr}'
    print(f'  {r.stdout.strip()}')


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
        dict(name='g', msrp_year='2026'),                               # orphaned msrp_year
        dict(name='h', msrp_trim='XLE'),                                # orphaned msrp_trim
        dict(name='i', msrp_source='KBB'),                              # orphaned msrp_source
    ]
    for row in rejected:
        assert build.price_problems([row]), f'gate accepted a bad row: {row}'
    assert not build.price_problems(
        [dict(name='ok', observed_price='1', price_year='2023', price_source='x')])


def check_recall_status_classification():
    """Pin the three outcomes fetch() must keep apart.

    A 400 means NHTSA has nothing to say, which is not the same as a successful
    response listing zero campaigns. Collapsing them made the cache assert zero
    recalls for years the CX-5 was plainly on sale.
    """
    import io
    import sys
    import urllib.error
    import fetch_recalls

    real = fetch_recalls.urllib.request.urlopen
    calls = []

    def fake(kind):
        def _open(url, timeout=None):
            calls.append(url)
            if kind == 'ok':
                return io.BytesIO(b'{"results": []}')
            raise urllib.error.HTTPError(url, kind, 'x', {}, None)
        return _open

    try:
        fetch_recalls.urllib.request.urlopen = fake('ok')
        assert fetch_recalls.fetch('m', 'x', 2021) == ([], 'ok'), \
            'a successful empty response is zero campaigns, not missing data'

        fetch_recalls.urllib.request.urlopen = fake(400)
        assert fetch_recalls.fetch('m', 'x', 2021) == (None, 'no_data'), \
            '400 must not be recorded as zero campaigns'

        calls.clear()
        fetch_recalls.urllib.request.urlopen = fake(503)
        # fetch() reports giving up on stderr; silence it so a passing suite
        # does not print something that reads like a failure in CI.
        stderr, sys.stderr = sys.stderr, io.StringIO()
        try:
            assert fetch_recalls.fetch('m', 'x', 2021, attempts=2) == (None, 'failed')
        finally:
            sys.stderr = stderr
        assert len(calls) == 2, f'5xx must retry, saw {len(calls)} attempt(s)'
    finally:
        fetch_recalls.urllib.request.urlopen = real

    carried = fetch_recalls.carry_forward({'by_year': {'2019': 1}, 'years_sampled': 1}, [2021])
    assert carried['stale'] and carried['comparable'] is False
    assert 'years_sampled' not in carried and carried['years_answered'] == 1
    assert carried['years_no_data'] == [], 'legacy entries must gain every current field'


def check_readme_counts(rows):
    """Stop README statistics drifting from the data they describe."""
    readme = (pathlib.Path(__file__).parent / 'README.md').read_text()
    no_study = sum(1 for r in rows if 'no study data' in (r['longevity_source'] or ''))
    assert f'{no_study} of the {len(rows)} vehicles have no published figure' in readme, \
        (f'README longevity count is stale: data says {no_study} of {len(rows)}')
    # Substring matching bit twice here. `str(4) in readme` matched "40,000",
    # and "4 of the 79 rows..." is a substring of "14 of the 79 rows...".
    # The bold delimiters already bound it, but assert the digit boundaries
    # explicitly rather than leaving correctness resting on a reader noticing
    # the asterisks.
    observed = sum(1 for r in rows if r.get('observed_price'))
    claim = (f'**{observed} of the {len(rows)} rows carry an observed '
             f'price today.**')
    pattern = (r'\*\*(?<!\d)' + str(observed) + r'(?!\d) of the (?<!\d)'
               + str(len(rows)) + r'(?!\d) rows carry an observed price today\.\*\*')
    assert re.search(pattern, readme), f'README is stale: expected "{claim}"'


if __name__ == '__main__':
    main()
