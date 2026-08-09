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

# Underscore-prefixed keys in data/inputs.json that are documentation, not a
# computational input engine.js reads. This is a closed allowlist on
# purpose, not a leading-underscore heuristic: a prefix test would let any
# *future* underscore-prefixed key opt itself out of check_js_engine_parity's
# drift comparison just by being named that way -- including a computational
# one someone wires into engine.js as `inp._something`. test_engine.mjs runs
# engine.js against the frozen fixture, not live INPUTS, so that comparison
# is the only check tying data/inputs.json to what test_engine.mjs actually
# exercises; silently exempting a key there is silently disabling the check.
# A new metadata key needs a conscious edit here, the same way an unknown
# provenance field is an error rather than a silent skip in price_problems.
METADATA_KEYS = {'_comment', '_currency'}


def main():
    # Price provenance, checked against the real rows. A price with no
    # recorded year, source, or trim is indistinguishable from a verified
    # one by the time it reaches the page.
    real = build.load()
    problems = build.price_problems(real)
    assert not problems, 'price provenance incomplete:\n  ' + '\n  '.join(problems)

    check_price_resolution()
    check_emitted_schema(real)
    check_row_keys(real)
    check_freeze_fixture_key_format(real)
    check_page_up_to_date(real)
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


def check_row_keys(rows):
    """price_problems() must enforce row identity, not just assert it holds.

    Row identity is (nameplate, trim), and it must be unique -- every map
    keyed by build.row_key -- the engine fixture, the recall cache, the
    workbook assertions -- collides the moment one nameplate appears twice
    with the same trim. main() already proves the real data satisfies these
    invariants (it asserts `not build.price_problems(real)` before this
    function runs), so this exercises the gate itself, against synthetic
    rows built to violate each invariant one at a time, rather than
    re-deriving the same logic test-side where a drift between the two could
    hide a build.py that stopped enforcing what this file asserts.
    """
    base = dict(price='20000', category='Test cat')

    dup = [dict(base, name='Dup', trim='base', trim_name='LX'),
           dict(base, name='Dup', trim='base', trim_name='LX')]
    assert build.price_problems(dup), \
        'two rows sharing a (nameplate, trim) key must be rejected'

    # Tiers are only meaningful once a nameplate has more than one row. Until
    # then 'unspecified' is correct and must not be mistaken for a real tier.
    unknown_trim = [dict(base, name='Unknown', trim='sport')]
    assert build.price_problems(unknown_trim), \
        'an unrecognised trim value must be rejected'

    # Partial population is the failure mode: one trim assigned and the rest
    # left unspecified would silently compare a tier against a non-tier.
    partial = [dict(base, name='Partial', trim='base', trim_name='LX'),
               dict(base, name='Partial', trim='unspecified')]
    assert build.price_problems(partial), \
        'a nameplate mixing a real tier with unspecified must be rejected'

    # Fully-populated sibling trims on one nameplate must pass. Both rows
    # share a nameplate and are the category's only members, so
    # category_ceiling excludes them from each other's peer set and finds
    # none -- this case is not exercising the price-plausibility ceiling,
    # only row identity.
    clean = [dict(base, name='Clean', trim='base', trim_name='LX'),
             dict(base, name='Clean', trim='loaded', trim_name='EX-L')]
    assert not build.price_problems(clean), \
        'fully-populated sibling tiers on one nameplate must not be rejected'


def check_freeze_fixture_key_format(rows):
    """freeze_fixture.py's writer must key by build.row_key(v), not bare name.

    test_engine.mjs reads `fixture[variant][v.key]`, and v.key is
    build.row_key(v) (see build.build_models). A fixture keyed by bare
    nameplate would silently disagree with that reader the moment a
    nameplate carries more than one trim -- with today's one-trim-per-name
    data it would instead make every entry compare as never-found, since
    'Name' and 'Name|unspecified' are different strings. Pins the format so
    the writer and the reader cannot drift apart again without this failing.

    Calls freeze_fixture.build_fixture() -- the exact code path
    `python3 freeze_fixture.py` uses to compute the fixture -- but never
    writes to data/engine-fixture.json, so it cannot clobber the frozen
    Python engine's output, the one piece of ground truth this codebase did
    not produce.
    """
    import shutil
    import freeze_fixture

    node = shutil.which('node')
    assert node, ('node is required to test freeze_fixture.py and was not '
                  'found. It is a development dependency only; the page '
                  'ships without it.')

    fixture = freeze_fixture.build_fixture(rows, node)
    expected = {build.row_key(v) for v in rows}
    for variant in ('full', 'workbook_oracle'):
        got = set(fixture[variant])
        assert got == expected, (
            f'freeze_fixture.py wrote {variant!r} keys that do not match '
            f'build.row_key(v) -- unexpected: {sorted(got - expected)[:3]}, '
            f'missing: {sorted(expected - got)[:3]}. The writer may have '
            f'reverted to keying by bare nameplate.')


def check_page_up_to_date(rows):
    """index.html on disk must be exactly what build.py would generate now.

    Every other check in this file runs against freshly generated dumps --
    engine.js invoked directly, models built straight from the CSV. None of
    that touches the committed index.html, so a hand-edit or a stale build
    committed by accident ships green anyway: the published page is the
    product, and nothing above proves the product matches the source.

    build.py --check already does this exact comparison; reuse it via
    build.render_current() rather than re-deriving "up to date" a second way
    that could quietly drift from the first.
    """
    html, updated, _ = build.render_current(rows)
    assert updated == html, (
        'index.html does not match what build.py would generate from the '
        'current sources -- run: python3 build.py')


def check_js_engine_parity(rows):
    """Run engine.js under Node against the frozen Python output.

    The 11 workbook figures prove the formula; this proves the port. Both are
    needed -- the workbook covers 11 of 79 vehicles at one input set.

    A missing Node must fail rather than skip. A skipped check reads exactly
    like a passing one.

    Dumps two model arrays, not one, via build.dump_variants(). build_models()
    resolves buy_price into the emitted 'price' field, so a vehicle with an
    observed price loses its raw placeholder there -- nulling observedPrice
    on that dict client-side cannot recover it. The workbook_oracle variant
    needs rows stripped of observed_price *before* build_models runs, same as
    main()'s workbook comparison, so its 'price' field is the true
    placeholder.
    """
    import json
    import shutil
    import subprocess

    node = shutil.which('node')
    assert node, ('node is required to test the cost engine and was not found. '
                  'It is a development dependency only; the page ships without it.')

    root = pathlib.Path(__file__).parent

    # data/inputs.json can drift from the inputs the fixture was frozen at
    # with this whole suite still green, because the model dump built below
    # is inputs-independent -- nothing else compares them. A drifted input
    # set makes every downstream "ok" claim false about the actual page.
    fixture = json.loads((root / 'data' / 'engine-fixture.json').read_text())
    # An underscore-prefixed key that is not in METADATA_KEYS must fail here
    # rather than silently fall out of the comparison below on either side --
    # otherwise a future computational input named with a leading underscore
    # would escape this check by naming convention alone, and test_engine.mjs
    # would keep reporting "ok" while checking engine.js against a frozen
    # fixture that never saw it.
    unknown = ({k for k in build.INPUTS if k.startswith('_')}
              | {k for k in fixture['_inputs'] if k.startswith('_')}) - METADATA_KEYS
    assert not unknown, (
        f'unrecognised underscore-prefixed key(s) {sorted(unknown)} in '
        'data/inputs.json or its frozen fixture -- add to test_build.py\'s '
        'METADATA_KEYS if this is documentation, not a computational input')
    # Compare only the computational inputs, not the allowlisted metadata.
    live = {k: v for k, v in build.INPUTS.items() if k not in METADATA_KEYS}
    frozen = {k: v for k, v in fixture['_inputs'].items() if k not in METADATA_KEYS}
    assert frozen == live, (
        'data/inputs.json has drifted from the inputs the oracle was frozen '
        'at -- regenerate data/engine-fixture.json with `python3 '
        'freeze_fixture.py`')

    dumped = build.dump_variants(rows, build.INPUTS)
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

    # Every provenance combination the gate is supposed to reject. Each row
    # carries trim='unspecified' so its rejection is pinned to the specific
    # violation under test, not incidentally caused by the trim check too --
    # otherwise these would be assertions that could never fail.
    rejected = [
        dict(name='a', trim='unspecified', observed_price='1', price_source='x'),  # no year
        dict(name='b', trim='unspecified', observed_price='1', price_year='2023'),  # no source
        dict(name='c', trim='unspecified', price_year='2023'),                  # orphaned year
        dict(name='d', trim='unspecified', price_source='x'),                   # orphaned source
        dict(name='e', trim='unspecified', msrp='1', msrp_year='2026',
             msrp_source='x'),                                          # no trim
        dict(name='f', trim='unspecified', msrp='1', msrp_trim='XLE',
             msrp_source='x'),                                          # no year
        dict(name='g', trim='unspecified', msrp_year='2026'),           # orphaned msrp_year
        dict(name='h', trim='unspecified', msrp_trim='XLE'),            # orphaned msrp_trim
        dict(name='i', trim='unspecified', msrp_source='KBB'),          # orphaned msrp_source
        dict(name='j', trim='unspecified', observed_price='1', price_year='2023',
             price_source='x'),                                 # no anchor
        # Plausibility. The CAD figure that prompted this was $60,585 for a
        # CR-V Hybrid whose real US price is nearer $35-40k, so the bound has
        # to be wide enough for a real Escalade and tight enough to catch a
        # currency error on a mainstream crossover.
        dict(name='k', trim='unspecified', observed_price='400000', price_year='2023',
             price_source='x', observed_price_odometer='40000'),   # too high
        dict(name='l', trim='unspecified', observed_price='250', price_year='2023',
             price_source='x', observed_price_odometer='40000'),   # too low
        dict(name='m', trim='unspecified', price='0'),                    # zero placeholder
    ]
    for row in rejected:
        assert build.price_problems([row]), f'gate accepted a bad row: {row}'
    # observed_price='1' was a placeholder-era convention meaning "amount
    # irrelevant, only provenance completeness matters." The plausibility
    # gate above retires that convention -- $1 is now itself implausible --
    # so this "everything is fine" row needs an amount inside PRICE_BOUNDS.
    assert not build.price_problems(
        [dict(name='ok', trim='unspecified', observed_price='31500', price_year='2023',
              price_source='x', observed_price_odometer='40000')])

    # category_ceiling must exclude the row under test from its own peer set.
    # Folding it in was the first version and does not work: an inflated
    # price becomes a candidate for the very max it is compared against, so
    # it becomes its own category's ceiling and can never exceed
    # CATEGORY_HEADROOM times itself. That silently passed the $60,585 CR-V
    # simulation in verification until this exclusion was added -- these two
    # cases pin the fix so it cannot regress.
    at_cap = [dict(name='p', trim='unspecified', category='Test cat', price='20000'),
              dict(name='q', trim='unspecified', category='Test cat', price='40000')]
    assert not build.price_problems(at_cap), \
        'exactly 2x a peer (not counting self) must not fire -- the bound is strict'
    over_cap = [dict(name='p', trim='unspecified', category='Test cat', price='20000'),
                dict(name='q', trim='unspecified', category='Test cat', price='40001')]
    assert build.price_problems(over_cap), \
        'a row priced over 2x its OTHER peers must be rejected even though ' \
        'it is also, trivially, the max of its own category'


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
