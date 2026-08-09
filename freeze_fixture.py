#!/usr/bin/env python3
"""Regenerate data/engine-fixture.json from the CURRENT engine.js and data.

The Python engine that originally produced the fixture is gone -- engine.js
is the only cost engine left, so this rebuilds the fixture by running
engine.js under Node, the same way test_build.py's check_js_engine_parity()
already does.

Run this only after a deliberate change to the model (engine.js) or to the
data (a price correction, a new vehicle) -- never to make a failing port
check pass. If test_build.py fails and the reason is a genuine formula bug in
engine.js, fix engine.js and rerun this only once the port is correct again.

    python3 freeze_fixture.py
"""
import json
import pathlib
import shutil
import subprocess
import sys

import build

ROOT = pathlib.Path(__file__).parent

FIXTURE_COMMENT = (
    "Froze the Python cost engine's output before it was deleted, to prove "
    "the JS port reproduces it to ~1e-12. Raw and unrounded on purpose. Now "
    "also the regression baseline for engine.js and the data: a deliberate "
    "change to the model or to a vehicle's price requires regenerating this "
    "file with `python3 freeze_fixture.py`. Never regenerate it just to "
    "make a failing port pass. Keyed by build.row_key(v), i.e. "
    "'(nameplate|trim)' -- e.g. 'Toyota Highlander Hybrid|unspecified' -- "
    "not by bare nameplate, because a nameplate stops being a unique key "
    "the moment it carries more than one trim."
)

# Runs engine.js under plain Node (no package.json in this repo, so a .js
# file is CommonJS by default -- require() works without ceremony). Reads
# the models this process dumped, writes back raw cpm per vehicle per
# variant. NO ROUNDING, same rule engine.js itself follows -- the fixture
# and the port must stay comparable to ~1e-12.
NODE_GENERATOR = """\
const { readFileSync, writeFileSync } = require('fs');
const VA = require('./engine.js');
const payload = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const out = {};
for (const variant of Object.keys(payload.models)) {
  out[variant] = {};
  for (const m of payload.models[variant]) {
    const cpm = VA.costPerMile(m, payload.inputs);
    if (!Number.isFinite(cpm)) {
      throw new Error(variant + ': ' + m.name + ': costPerMile returned ' + cpm);
    }
    out[variant][m.key] = cpm;
  }
}
writeFileSync(process.argv[3], JSON.stringify(out));
"""


def build_fixture(rows, node):
    """Compute the fixture dict for `rows`, without writing to disk.

    Every entry is keyed by build.row_key(v) -- '(nameplate|trim)' -- not by
    bare nameplate, so this agrees with what test_engine.mjs looks up via
    `fixture[variant][v.key]`. Split out of main() so a test can pin this key
    format against build.row_key() directly, without going anywhere near the
    real data/engine-fixture.json -- that file is the only record left of the
    deleted Python engine's output, and nothing in a test run may overwrite it.
    """
    # Same two variants check_js_engine_parity() feeds the engine: 'full'
    # from the real rows, 'workbook_oracle' from rows with observed_price
    # and msrp stripped before build_models runs.
    dumped = build.dump_variants(rows, build.INPUTS)

    # Raw, unrounded price and its basis, straight from buy_price() on the
    # same (real or stripped) rows -- build_models() rounds 'price' to an
    # int for the page, which the fixture deliberately does not do.
    raw = {
        'full': {build.row_key(v): build.buy_price(v, build.INPUTS) for v in rows},
        'workbook_oracle': {build.row_key(v): build.buy_price(v, build.INPUTS)
                            for v in build.strip_for_oracle(rows)},
    }

    models_path = ROOT / 'freeze-fixture-models.json'
    cpm_path = ROOT / 'freeze-fixture-cpm.json'
    script_path = ROOT / 'freeze-fixture-gen.js'
    models_path.write_text(json.dumps({'models': dumped, 'inputs': build.INPUTS}))
    script_path.write_text(NODE_GENERATOR)
    try:
        r = subprocess.run([node, str(script_path), str(models_path), str(cpm_path)],
                           cwd=ROOT, capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit(f'engine.js failed while regenerating the fixture:\n'
                     f'{r.stdout}{r.stderr}')
        cpms = json.loads(cpm_path.read_text())
    finally:
        models_path.unlink(missing_ok=True)
        cpm_path.unlink(missing_ok=True)
        script_path.unlink(missing_ok=True)

    return {
        '_comment': FIXTURE_COMMENT,
        '_inputs': build.INPUTS,
        'full': {
            name: {'basis': raw['full'][name][1],
                   'cpm': cpms['full'][name],
                   'price': raw['full'][name][0]}
            for name in cpms['full']
        },
        'workbook_oracle': {
            name: {'basis': raw['workbook_oracle'][name][1],
                   'cpm': cpms['workbook_oracle'][name],
                   'price': raw['workbook_oracle'][name][0]}
            for name in cpms['workbook_oracle']
        },
    }


def main():
    node = shutil.which('node')
    if not node:
        sys.exit('node is required to regenerate the fixture and was not '
                 'found. It is a development dependency only; the page '
                 'ships without it.')

    rows = build.load()
    problems = build.price_problems(rows)
    if problems:
        sys.exit('price provenance is incomplete:\n  ' + '\n  '.join(problems))

    fixture = build_fixture(rows, node)
    fixture_path = ROOT / 'data' / 'engine-fixture.json'
    fixture_path.write_text(json.dumps(fixture, indent=2, sort_keys=True) + '\n')
    print(f'wrote data/engine-fixture.json '
          f'({len(fixture["full"])} vehicles, full + workbook_oracle)')


if __name__ == '__main__':
    main()
