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

    # Same treatment for the hand-edited assumptions. A shipped ratio below 1
    # would invert the repair model and leave every other check in this file
    # green, so the suite has to fail on the real data/inputs.json, not only
    # on the synthetic rows check_input_ranges() constructs.
    problems = build.input_problems(build.INPUTS)
    assert not problems, 'data/inputs.json out of range:\n  ' + '\n  '.join(problems)

    check_input_ranges()
    check_collapse_order()
    check_complaint_classification()
    check_complaint_columns()
    check_export()
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


def check_input_ranges():
    """input_problems() must reject a repair spread ratio below 1.

    The ratio is the one assumption the README tells a reader to hand-edit
    ("set it to 1 to turn it off"), and 0.5 is the plausible typo for "half
    the effect". It is not half the effect: the exponent's sign flips, so the
    most reliable vehicles get the biggest repair reserve. Nothing else in
    this repo can catch it -- regenerating the fixture at 0.5 makes the
    engine parity check, the workbook oracle, and every multiplier assertion
    agree with the inverted model -- so these cases exercise the gate itself,
    the same way check_row_keys() exercises the row-identity gate.
    """
    def problems(ratio):
        return build.input_problems(dict(build.INPUTS,
                                         repair_cost_spread_ratio=ratio))

    for bad in (0.5, 0, -2.66, 0.999):
        found = problems(bad)
        assert found, f'a spread ratio of {bad} inverts the model and must be rejected'
        assert any('repair_cost_spread_ratio' in p for p in found), \
            f'the rejection must name the key; got: {found}'

    # 1 is the documented off switch, not an error, and the shipped default
    # must pass. A gate that rejected either would make the feature
    # unturnoffable or the repo unbuildable.
    assert not problems(1), 'a ratio of 1 is the documented off switch and must pass'
    assert not problems(2.66), 'the shipped default must pass'

    # A missing or non-numeric ratio reaches engine.js as NaN, which renders
    # a blank chart rather than raising. Unknown has to be an error here for
    # the same reason unknown provenance is an error in price_problems().
    missing = {k: v for k, v in build.INPUTS.items()
               if k != 'repair_cost_spread_ratio'}
    assert build.input_problems(missing), \
        'a missing spread ratio must be rejected, not defaulted'
    assert problems('2.66'), 'a quoted ratio is not a number and must be rejected'
    assert problems(True), 'a boolean ratio must be rejected, not read as 1'

    # json.load() accepts the non-standard NaN, Infinity and -Infinity tokens
    # by default, so all three can arrive from a hand-edited inputs.json.
    # None is caught by the `< 1` comparison: NaN < 1 and Infinity < 1 are
    # both False, and -Infinity would be swallowed by the inversion message
    # rather than named for what it is. NaN is the dangerous one -- it makes
    # every cost per mile NaN, and the page draws an empty chart instead of
    # failing.
    for bad in (float('nan'), float('inf'), float('-inf')):
        found = problems(bad)
        assert found, f'a ratio of {bad} is not finite and must be rejected'
        assert any('finite' in p for p in found), \
            f'{bad} must be named as non-finite, not mistaken for an inverted ratio; got: {found}'


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


def check_collapse_order():
    """Run the #27 regression test: frontier across all trims, then collapse.

    Lives in Node because it exercises the shipped page logic, extracted from
    index.html rather than reimplemented -- a reimplementation would only test
    the copy.
    """
    import shutil
    import subprocess
    node = shutil.which('node')
    assert node, 'node is required to test the collapse order and was not found'
    root = pathlib.Path(__file__).parent
    r = subprocess.run([node, str(root / 'test_collapse.mjs')],
                       cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, f'collapse-order check failed:\n{r.stdout}{r.stderr}'
    print(f'  {r.stdout.strip()}')


def check_export():
    """Run the CSV export test: every ranked row, every assumption, escaped.

    Same shape as check_collapse_order -- the functions under test are pulled
    out of the shipped index.html, so this fails if the page's own export
    logic regresses.
    """
    import shutil
    import subprocess
    node = shutil.which('node')
    assert node, 'node is required to test the CSV export and was not found'
    root = pathlib.Path(__file__).parent
    r = subprocess.run([node, str(root / 'test_export.mjs')],
                       cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, f'export check failed:\n{r.stdout}{r.stderr}'
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

    # category_ceiling must also exclude a row's SIBLINGS -- every other row
    # sharing its nameplate -- not just the row itself. Three trims of one
    # nameplate, all inflated to the same implausible price, plus a genuine
    # same-category peer at a normal price as the anchor. Without the
    # same-nameplate exclusion, the three siblings would be one another's
    # peers and each other's ceiling: an inflated price becomes a candidate
    # for the very max it is compared against, so none of them could ever
    # exceed CATEGORY_HEADROOM times a sibling inflated by the same amount.
    # That is exactly the failure mode this check exists to catch --
    # sourcing all of a nameplate's trims from one bad page. The anchor is
    # what makes rejection possible at all: it sets a real ceiling the
    # siblings cannot reach together once they can no longer vouch for each
    # other.
    sibling_price = '60585'  # the CAD CR-V Hybrid figure that motivated this gate
    siblings_inflated = [
        dict(name='Sib', trim='base', trim_name='LX', category='Test cat',
             price=sibling_price),
        dict(name='Sib', trim='volume', trim_name='EX', category='Test cat',
             price=sibling_price),
        dict(name='Sib', trim='loaded', trim_name='EX-L', category='Test cat',
             price=sibling_price),
        dict(name='Anchor', trim='unspecified', category='Test cat', price='25000'),
    ]
    sibling_problems = build.price_problems(siblings_inflated)
    assert sum(1 for p in sibling_problems if p.startswith('Sib:')) == 3, \
        ('all three inflated sibling trims must be rejected once a genuine '
         f'peer sets a real ceiling; got: {sibling_problems}')
    assert not any(p.startswith('Anchor:') for p in sibling_problems), \
        f'the genuine peer itself must not be flagged; got: {sibling_problems}'

    # Two DIFFERENT nameplates, both inflated in the same category at the
    # same time, are a gap this check does NOT close -- documented as an
    # expected pass, not a silent omission. Each nameplate is excluded only
    # from its OWN peer set, so two distinct nameplates remain each other's
    # peers and can still mask one another, same as the pre-fix behavior for
    # this specific case. See category_ceiling's docstring.
    two_plates_inflated = [
        dict(name='CR-V Hybrid', trim='unspecified', category='Test cat', price='60585'),
        dict(name='RAV4 Hybrid', trim='unspecified', category='Test cat', price='61000'),
    ]
    assert not build.price_problems(two_plates_inflated), \
        ('two different nameplates both inflated in the same category are a '
         'known, undocumented-as-closed gap -- this must still pass, and a '
         'failure here means the gap silently closed or someone narrowed '
         "the exclusion in a way that changes this contract without "
         "updating category_ceiling's docstring")

    # A malformed price on one row must not raise while category_ceiling
    # computes a DIFFERENT row's ceiling. Peers are parsed before their own
    # per-row validation has necessarily run (price_problems iterates rows in
    # order), so a bad peer has to be skipped rather than crash the row
    # actually under test.
    malformed_peer = [
        dict(name='Malformed', trim='unspecified', category='Test cat', price='abc'),
        dict(name='Valid', trim='unspecified', category='Test cat', price='22000'),
    ]
    malformed_problems = build.price_problems(malformed_peer)
    assert any(p.startswith('Malformed:') and 'not a number' in p
              for p in malformed_problems), \
        f'a malformed price must be reported on its own row; got: {malformed_problems}'
    assert not any(p.startswith('Valid:') for p in malformed_problems), \
        ("a malformed peer's price must not raise while validating a "
         f'different row, nor produce a problem attributed to that other '
         f'row; got: {malformed_problems}')


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


def check_complaint_classification():
    """is_expensive() must key off the subsystem, not the whole string.

    NHTSA returns a comma-separated component list, so a complaint naming
    both a cosmetic and an expensive subsystem is expensive. Matching the
    raw string with `in` would also catch 'ENGINE' inside 'ENGINE AND
    ENGINE COOLING' by accident and miss 'POWER TRAIN' entirely when it
    arrives second in the list.
    """
    import fetch_complaints as fc
    for field in ('ENGINE', 'POWER TRAIN', 'SEATS, ENGINE',
                  'ENGINE AND ENGINE COOLING', 'SERVICE BRAKES, HYDRAULIC'):
        assert fc.is_expensive(field), f'{field!r} should count as expensive'
    for field in ('SEATS', 'STRUCTURE', 'UNKNOWN OR OTHER', '', 'EXTERIOR LIGHTING'):
        assert not fc.is_expensive(field), f'{field!r} should not count as expensive'

    # A component that merely CONTAINS an expensive subsystem's name is not
    # that subsystem. This is the case that separates split-then-prefix from
    # substring matching -- every other fixture in this test passes under
    # both, so without it the function's actual logic is untested.
    assert not fc.is_expensive('CHECK ENGINE INDICATOR LAMP'), \
        'a component merely containing "ENGINE" is not an engine complaint'
    assert not fc.is_expensive('BACKUP CAMERA, EXTERIOR LIGHTING'), \
        'no part of this list starts with an expensive subsystem'

    # A share is a ratio, so it must not move with the number of complaints.
    few = [{'components': 'ENGINE'}, {'components': 'SEATS'}]
    many = [{'components': 'ENGINE'}] * 50 + [{'components': 'SEATS'}] * 50
    assert fc.severity_share(few) == fc.severity_share(many) == 0.5, \
        'severity share must be volume-independent'

    # Zero complaints is not a share of zero, and the column writer has to
    # survive that: formatting None crashed main() AFTER the multi-minute
    # fetch had already written complaints.json, so the run looked half-done
    # and the fix was invisible until the next full refetch.
    assert fc.severity_share([]) is None, \
        'a nameplate with no complaints has no share, not a share of zero'
    assert fc.columns_for({'severity_share': None, 'n': 0, 'years': [2019]}) \
        == ('', '', ''), 'a missing share must write three empty columns, not raise'
    assert fc.columns_for(None) == ('', '', ''), \
        'a nameplate with no entry at all must write three empty columns'
    assert fc.columns_for({'severity_share': 0.6, 'n': 120, 'years': [2019, 2023]}) \
        == ('0.6000', '120', '2019|2023'), \
        'a complete entry must still write all three columns'
    print('  ok: complaint severity classification')


def check_complaint_columns():
    """A partial complaint record must be rejected, not half-used.

    Same rule the price columns already follow: metadata claiming provenance
    the figure does not have reads exactly like a verified figure once it
    reaches the page.
    """
    base = dict(price='20000', category='Test cat', name='T', trim='unspecified')
    full = dict(base, complaint_severity_share='0.6', complaint_n='120',
                complaint_years='2019|2021|2023')
    assert not build.price_problems([full]), \
        'a complete complaint record must pass'
    for missing in ('complaint_severity_share', 'complaint_n', 'complaint_years'):
        partial = dict(full)
        partial[missing] = ''
        assert build.price_problems([partial]), \
            f'a complaint record missing {missing} must be rejected'
    # A share is a fraction. 60 is a percentage someone forgot to divide.
    assert build.price_problems([dict(full, complaint_severity_share='60')]), \
        'a severity share outside 0-1 must be rejected'
    print('  ok: complaint column provenance')


if __name__ == '__main__':
    main()
