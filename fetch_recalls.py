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


def fetch(make, model, year):
    q = urllib.parse.urlencode(dict(make=make, model=model, modelYear=year))
    url = f'https://api.nhtsa.gov/recalls/recallsByVehicle?{q}'
    try:
        with urllib.request.urlopen(url, timeout=30) as fh:
            return json.load(fh).get('results') or []
    except Exception as exc:                      # transient API failure
        print(f'  ! {make} {model} {year}: {exc}', file=sys.stderr)
        return None


def main():
    names = [r['name'] for r in csv.DictReader(open(ROOT / 'data' / 'vehicles.csv'))]
    out = {}
    for name in names:
        make, model = split_name(name)
        if not make:
            print(f'  ? unparsed make: {name}', file=sys.stderr)
            continue
        counts, powertrain, ok = {}, set(), 0
        for y in YEARS:
            rs = fetch(make, model, y)
            if rs is None:
                continue
            ok += 1
            counts[y] = len(rs)
            for r in rs:
                comp = (r.get('Component') or '').upper()
                if 'TRANSMISSION' in comp or 'POWER TRAIN' in comp:
                    powertrain.add(y)
        if not ok:
            continue
        out[name] = {
            'make': make, 'model': model, 'by_year': counts,
            'per_year': round(sum(counts.values()) / ok, 2),
            'powertrain_years': sorted(powertrain),
            'years_sampled': ok,
        }
        print(f'{name:<40} {out[name]["per_year"]:>6} campaigns/yr'
              f'{"  POWERTRAIN" if powertrain else ""}')

    (ROOT / 'data' / 'recalls.json').write_text(json.dumps(out, indent=2) + '\n')
    print(f'\nwrote data/recalls.json for {len(out)}/{len(names)} nameplates')


if __name__ == '__main__':
    main()
