#!/usr/bin/env python3
"""Cache NHTSA recall-campaign counts per nameplate into data/recalls.json.

Recalls, unlike complaints, are manufacturer/regulator actions rather than
consumer reports, so the count does not scale with how many units are on the
road. Probed against 10 nameplates: Ford Explorer 117 vs Toyota RAV4 31, and
Explorer is not four times RAV4's volume. That makes it usable for comparing
nameplates, which raw complaint counts demonstrably are not.

Run: python3 fetch_recalls.py    (a few minutes; writes data/recalls.json)
"""
import csv
import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).parent
YEARS = (2019, 2021, 2023)          # sampled, not exhaustive -- see README
MAKES = ('Chevrolet', 'GMC', 'Ford', 'Toyota', 'Lexus', 'Honda', 'Acura', 'Nissan',
         'Infiniti', 'Jeep', 'Ram', 'Dodge', 'Chrysler', 'Kia', 'Hyundai', 'Genesis',
         'Subaru', 'Mazda', 'Volkswagen', 'Cadillac', 'Lincoln', 'Buick', 'Volvo',
         'Land Rover', 'BMW', 'Mercedes-Benz', 'Audi', 'Rivian', 'Tesla')


def split_name(name):
    """'Toyota Sequoia (pre-2023 5.7 V8)' -> ('Toyota', 'Sequoia')."""
    base = re.sub(r'\s*\(.*?\)', '', name).strip()
    for mk in sorted(MAKES, key=len, reverse=True):
        if base.lower().startswith(mk.lower()):
            return mk, base[len(mk):].strip()
    return None, base


def fetch(make, model, year, attempts=3):
    """Return (results, status).

    status is 'ok', 'no_data' when NHTSA answers 400, or 'failed' when the
    request never succeeded.

    A 400 does NOT mean the vehicle was not sold. The Mazda CX-5 returns 400
    for 2021 and 2023 and is obviously sold in both. It means NHTSA has nothing
    to say about that combination, and "nothing to say" is not "zero recalls".
    Recording a 0 for those years asserts a fact the API never supplied, so
    no_data years are omitted from by_year entirely rather than counted.
    """
    q = urllib.parse.urlencode(dict(make=make, model=model, modelYear=year))
    url = f'https://api.nhtsa.gov/recalls/recallsByVehicle?{q}'
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=30) as fh:
                return json.load(fh).get('results') or [], 'ok'
        except urllib.error.HTTPError as exc:
            if exc.code == 400:
                return None, 'no_data'
            if exc.code < 500:
                return None, 'failed'
        except Exception:
            pass
        if attempt + 1 < attempts:
            time.sleep(2 ** attempt)
    print(f'  ! {make} {model} {year}: gave up after {attempts} attempts',
          file=sys.stderr)
    return None, 'failed'


def carry_forward(entry, failed_years):
    """Reuse a previous entry, normalised to the current schema and marked stale.

    Preserving a raw previous entry leaves two shapes in one file, so a consumer
    reading years_offered gets None for exactly the rows that are least
    trustworthy. Normalise the key, and say plainly that the row was not
    refreshed rather than letting it pass as current.
    """
    entry = dict(entry)
    for old in ('years_sampled', 'years_offered'):   # earlier schemas
        if old in entry:
            entry['years_answered'] = entry.pop(old)
    entry.setdefault('years_answered', len(entry.get('by_year') or {}))
    entry.setdefault('years_requested', len(YEARS))
    entry.setdefault('years_no_data', [])
    entry['stale'] = True
    entry['comparable'] = False
    entry['failed_years'] = sorted(failed_years)
    return entry


def main():
    names = [r['name'] for r in csv.DictReader(open(ROOT / 'data' / 'vehicles.csv'))]
    cache_path = ROOT / 'data' / 'recalls.json'
    previous = json.loads(cache_path.read_text()) if cache_path.exists() else {}

    out, kept, dropped = {}, [], []
    for name in names:
        make, model = split_name(name)
        if not make:
            print(f'  ? unparsed make: {name}', file=sys.stderr)
            continue

        counts, powertrain, failed, unknown = {}, set(), [], []
        for y in YEARS:
            rs, status = fetch(make, model, y)
            if status == 'failed':
                failed.append(y)
                continue
            if status == 'no_data':
                unknown.append(y)       # omitted, not recorded as zero
                continue
            counts[y] = len(rs)
            for r in rs:
                comp = (r.get('Component') or '').upper()
                if 'TRANSMISSION' in comp or 'POWER TRAIN' in comp:
                    powertrain.add(y)

        # A partial refresh must never overwrite a complete one. An average over
        # two years is not comparable to an average over three, and silently
        # publishing the short one understates that nameplate against its peers.
        if failed:
            if name in previous:
                out[name] = carry_forward(previous[name], failed)
                kept.append(name)
            else:
                dropped.append(name)
            print(f'  ! {name}: years {failed} failed; '
                  f'{"kept previous value" if name in previous else "no data"}',
                  file=sys.stderr)
            continue

        if not counts:                       # NHTSA answered for no sampled year
            dropped.append(name)
            continue

        answered = len(counts)
        out[name] = {
            'make': make, 'model': model, 'by_year': counts,
            'per_year': round(sum(counts.values()) / answered, 2),
            'powertrain_years': sorted(powertrain),
            'years_answered': answered,
            'years_requested': len(YEARS),
            'years_no_data': sorted(unknown),
            # per_year averages over years_answered, not years_requested.
            # Ranking nameplates on it without checking compares different
            # denominators.
            # NHTSA treats "Escape Hybrid" and "Escape" as different models and
            # returns wildly different counts -- 1 against 19 for 2021 -- and not
            # as a subset, since CR-V Hybrid exceeds CR-V for 2023. Querying a
            # variant name therefore under- or over-states the nameplate. See #16.
            'variant_query': model != model.split(' Hybrid')[0].split(' (')[0],
            'comparable': answered == len(YEARS),
        }
        print(f'{name:<40} {out[name]["per_year"]:>6} campaigns/yr'
              f'  ({answered}/{len(YEARS)} yr)'
              f'{"  POWERTRAIN" if powertrain else ""}')

    # Atomic replace, so an interrupted run cannot leave a truncated cache.
    tmp = cache_path.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(out, indent=2, sort_keys=True) + '\n')
    tmp.replace(cache_path)

    print(f'\nwrote data/recalls.json for {len(out)}/{len(names)} nameplates')
    if kept:
        print(f'  {len(kept)} kept a previous value after a failed refresh')
    if dropped:
        print(f'  {len(dropped)} have no usable data: {", ".join(dropped[:5])}'
              f'{" ..." if len(dropped) > 5 else ""}')


if __name__ == '__main__':
    main()
