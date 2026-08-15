#!/usr/bin/env python3
"""Cache NHTSA consumer complaints per nameplate into data/complaints.json.

Sibling of fetch_recalls.py, and deliberately the same shape: same
split_name(), same YEARS, same rule that a 400 is not a zero.

What is stored is a SHARE, not a count. Complaint counts scale with how many
of a vehicle were sold and NHTSA publishes no denominator -- in this fleet the
highest counts belong to the RAV4 and CR-V, the best-selling crossovers in the
country. The fraction of a vehicle's own complaints that name an expensive
subsystem has the fleet size cancel out of it exactly.

Run: python3 fetch_complaints.py   (several minutes; rewrites data/complaints.json
                                    and the three complaint columns in
                                    data/vehicles.csv)
"""
import csv
import json
import pathlib
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
    make, model = fetch_recalls.split_name(name)
    if not make:
        return name, None
    got, years = [], []
    for y in YEARS:
        res, status = fetch(make, model, y)
        if status == 'ok':
            got.extend(res)
            years.append(y)
    if not years:
        return name, None
    return name, {'severity_share': severity_share(got), 'n': len(got), 'years': years}


def main():
    rows = list(csv.DictReader(open(ROOT / 'data' / 'vehicles.csv')))
    names = sorted({r['name'] for r in rows})
    out = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        for name, entry in pool.map(one, names):
            if entry:
                out[name] = entry
            print(f'{name}: {entry["n"] if entry else "no data"}', flush=True)
    (ROOT / 'data' / 'complaints.json').write_text(
        json.dumps(out, indent=1, sort_keys=True) + '\n')
    print(f'wrote data/complaints.json for {len(out)}/{len(names)} nameplates')


if __name__ == '__main__':
    main()
