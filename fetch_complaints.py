#!/usr/bin/env python3
"""Cache NHTSA consumer complaints per nameplate into data/complaints.json.

Sibling of fetch_recalls.py, and deliberately the same shape: same
split_name(), same YEARS, same rule that a 400 is not a zero.

What is stored is a SHARE, not a count. Complaint counts scale with how many
of a vehicle were sold and NHTSA publishes no denominator -- in this fleet the
highest counts belong to the RAV4 and CR-V, the best-selling crossovers in the
country. The fraction of a vehicle's own complaints that name an expensive
subsystem has the fleet size cancel out of it exactly.

A DEGRADED RUN WRITES NOTHING. If any model-year query failed -- a timeout, a
gateway 500, anything that is not a clean answer or NHTSA's "no data" 400 --
this script leaves data/complaints.json and data/vehicles.csv exactly as it
found them, prints which nameplates failed, and exits 1. A 400 is not a
failure; it is NHTSA saying it has nothing for that model year.

The cached files are the better data. A partial pull silently understates a
nameplate's count, which can drop it below complaint_min_n, flip it from
measured to judgment and change its cost, with nothing in the persisted files
to show for it -- a warning printed after the write is a warning nobody reads
six months later. Refusing to write is the only signal that survives.

Run: python3 fetch_complaints.py   (several minutes; rewrites data/complaints.json)
     python3 fetch_complaints.py --allow-partial   (write anyway, deliberately)
"""
import csv
import json
import pathlib
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import fetch_recalls

ROOT = pathlib.Path(__file__).parent
YEARS = fetch_recalls.YEARS

# Subsystems whose failure is a repair bill rather than a nuisance. The repair
# reserve models dollars, so this is the half of the complaint stream that
# speaks to it.
EXPENSIVE = (
    'ENGINE',
    'POWER TRAIN',
    'ELECTRICAL SYSTEM',
    'FUEL SYSTEM',
    'SUSPENSION',
    'STEERING',
    'SERVICE BRAKES',
)


def is_expensive(component_field):
    """True when any subsystem in NHTSA's comma-separated list is expensive.

    Split first, then prefix-match each part. A substring test against the
    whole field would be both too eager and too lax.
    """
    for part in (component_field or '').split(','):
        part = part.strip().upper()
        if any(part.startswith(e) for e in EXPENSIVE):
            return True
    return False


def severity_share(complaints):
    """Fraction of complaints naming an expensive subsystem, or None if none."""
    if not complaints:
        return None
    return sum(1 for c in complaints if is_expensive(c.get('components'))) / len(complaints)


def columns_for(entry):
    """The three CSV cells for one nameplate, or three blanks when it has none.

    A nameplate NHTSA answers for with zero complaints has years but no
    share, and formatting None raised TypeError here -- after the fetch had
    already written complaints.json, so the run looked half-done. A missing
    share is no evidence, exactly like no data at all, and build.py rejects a
    row carrying two of the three columns anyway.
    """
    if not entry or entry.get('severity_share') is None:
        return '', '', ''
    return (f"{entry['severity_share']:.4f}",
            str(entry['n']),
            '|'.join(str(y) for y in entry['years']))


def fetch(make, model, year, attempts=4):
    """Return (results, status): 'ok', 'no_data' on a 400, or 'failed'.

    The gateway answers 200 with {"message": "Endpoint request timed out"} and
    no results key on large queries -- a failure wearing a success code. The
    Ford F-150 is unreachable without retrying it. Treating that body as an
    empty result would record a popular truck as complaint-free.
    """
    q = urllib.parse.urlencode(dict(make=make, model=model, modelYear=year))
    url = f'https://api.nhtsa.gov/complaints/complaintsByVehicle?{q}'
    for _ in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=60) as fh:
                payload = json.loads(fh.read().decode())
        except urllib.error.HTTPError as exc:
            if exc.code == 400:
                return None, 'no_data'
            continue
        except Exception:
            continue
        if 'results' not in payload:
            continue
        return payload['results'], 'ok'
    return None, 'failed'


def one(name):
    """Return (name, entry, failed_years).

    'no_data' and 'failed' both skip the year, but they are not the same
    fact: a 400 means NHTSA has nothing for that model year, a failure means
    we could not ask. Counting failures separately is what keeps a degraded
    run from reading like a vehicle with little history.
    """
    make, model = fetch_recalls.split_name(name)
    if not make:
        return name, None, 0
    got, years, failed = [], [], 0
    for y in YEARS:
        res, status = fetch(make, model, y)
        if status == 'ok':
            got.extend(res)
            years.append(y)
        elif status == 'failed':
            failed += 1
    if not years:
        return name, None, failed
    return name, {'severity_share': severity_share(got), 'n': len(got),
                  'years': years}, failed


def collect(names):
    """Fetch every nameplate. Returns (entries, failures-by-nameplate)."""
    out, failures = {}, {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        for name, entry, failed in pool.map(one, names):
            if entry:
                out[name] = entry
            if failed:
                failures[name] = failed
            note = f' -- {failed} of {len(YEARS)} model years FAILED' if failed else ''
            print(f'{name}: {entry["n"] if entry else "no data"}{note}', flush=True)
    return out, failures


def write_outputs(out, root=ROOT):
    """Persist the cache and rewrite the three derived columns. Returns rows."""
    (root / 'data' / 'complaints.json').write_text(
        json.dumps(out, indent=1, sort_keys=True) + '\n')

    # Write the derived columns back into the dataset. Hand-entering 79 rows
    # from a file this script just produced would be transcription with no
    # judgment in it, and the two copies would drift on the first refetch.
    path = root / 'data' / 'vehicles.csv'
    with open(path, newline='') as fh:
        reader = csv.DictReader(fh)
        fieldnames = list(reader.fieldnames)
        rows = list(reader)
    for col in ('complaint_severity_share', 'complaint_n', 'complaint_years'):
        if col not in fieldnames:
            fieldnames.append(col)
    for r in rows:
        (r['complaint_severity_share'], r['complaint_n'],
         r['complaint_years']) = columns_for(out.get(r['name']))
    with open(path, 'w', newline='') as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def persist(out, failures, root=ROOT, allow_partial=False):
    """Write the results, or refuse to. Returns the process exit code.

    A failed query and a vehicle with little history are indistinguishable
    once they reach the files, so a degraded run must not reach them. The
    cached copy is the better data: it was written by a run that answered
    every query, and overwriting it with a partial pull is the loss. Only
    --allow-partial, typed on purpose, lets a gap through.
    """
    if failures and not allow_partial:
        print(f'REFUSED: {sum(failures.values())} model-year queries failed across '
              f'{len(failures)} nameplates, so this pull understates them: '
              + ', '.join(sorted(failures)))
        print('data/complaints.json and data/vehicles.csv are UNCHANGED. A partial '
              'pull can drop a nameplate below complaint_min_n and flip it from '
              'measured to judgment with nothing in the files to show for it. '
              'Re-run, or pass --allow-partial to overwrite the cache anyway.')
        return 1
    rows = write_outputs(out, root)
    print(f'wrote data/complaints.json and updated {rows} rows '
          f'in data/vehicles.csv ({len(out)} with evidence)')
    if failures:
        print(f'WARNING: written with --allow-partial despite {sum(failures.values())} '
              f'failed queries across {len(failures)} nameplates, which now '
              f'understate their complaint history: ' + ', '.join(sorted(failures)))
    else:
        print('every model-year query answered: no silent gaps')
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    allow_partial = '--allow-partial' in argv
    rows = list(csv.DictReader(open(ROOT / 'data' / 'vehicles.csv')))
    names = sorted({r['name'] for r in rows})
    out, failures = collect(names)
    return persist(out, failures, allow_partial=allow_partial)


if __name__ == '__main__':
    raise SystemExit(main())
