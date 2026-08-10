/* Pins the CSV export: it carries every ranked row, not the 24 the ranked
   list draws, and a risk sentence full of commas cannot shift a column.

   Extracts the shipped csvEscape/csvRow/buildExport straight out of
   index.html rather than reimplementing them, same as test_collapse.mjs --
   reimplementing would only test the copy. */
import { readFileSync } from 'node:fs';

const html = readFileSync('./index.html', 'utf8');

function extract(pattern, label) {
  const m = html.match(pattern);
  if (!m) throw new Error(`could not find ${label} in index.html -- the test is stale, fix it rather than deleting it`);
  return m[0];
}

const escSrc = extract(/function csvEscape\(s\)\{[\s\S]*?\n\}/, 'csvEscape');
const rowSrc = extract(/function csvRow\(cells\)\{[^\n]*\}/, 'csvRow');
const buildSrc = extract(/function buildExport\(st\)\{[\s\S]*?\n\}/, 'buildExport');

const buildExport = new Function(
  'INPUTS', 'DEFAULTS', 'FIELDS', 'AXES', 'W', 'PRESET', 'FILT', 'SEL', 'location', 'st',
  `${escSrc}\n${rowSrc}\n${buildSrc}\nreturn buildExport(st);`);
const csvEscape = new Function(`${escSrc}\nreturn csvEscape;`)();

/* Both line terminators end a record to a spreadsheet, so both have to be
   quoted. A bare CR was the miss: it is invisible in a diff and splits a row
   in half in Excel while every LF-only test still passes. */
for (const [label, value] of [['CR', 'Runs hot\rper NHTSA'],
  ['CRLF', 'Runs hot\r\nper NHTSA'], ['LF', 'Runs hot\nper NHTSA']]) {
  const out = csvEscape(value);
  if (out[0] !== '"' || out[out.length - 1] !== '"') {
    throw new Error(`a ${label} inside a field was left unquoted: ${JSON.stringify(out)}`);
  }
}

const INPUTS = {
  annual_miles: 60000, gas_per_gal: 3.55,
  repair_reserve_per_mile: { under_100k: 0.03, '100k_to_150k': 0.06, over_150k: 0.1 },
  financing_mode: 'cash', cash_opportunity_rate: 0.045, loan_apr: 0.065,
  down_payment_pct: 0.2, avg_outstanding_balance_factor: 0.55,
  sales_tax_rate: 0.07, industry_avg_5yr_deprec: 0.418, repair_cost_spread_ratio: 2.66,
};
const DEFAULTS = { ...INPUTS, annual_miles: 55000 };  // annual_miles is edited
const FIELDS = [{ k: 'annual_miles', l: 'Annual miles' }, { k: 'gas_per_gal', l: 'Gas $/gal' }];
const AXES = [['Cost'], ['Quality'], ['Longevity'], ['Efficiency'], ['Reliability'], ['Comfort']];
const W = [25, 15, 15, 10, 20, 15];

function fakeRow(i) {
  return {
    name: `Vehicle ${i}`, trimName: '', tier: 1, cat: 'Full-size BOF SUV',
    cpm: 0.9 + i / 1000, peryr: 50000, price: 45000, priceBasis: 'placeholder',
    mpg: 22, fuel: 'Gas', onFront: i === 0, total: 70, value: 60, cost: 55.5,
    quality: 80, longevity: 70, reliability: 60, comfort: 50, efficiency: 40,
    db55: 66.5, dbMeasured: true, transName: '10-speed auto', engineName: 'V8',
    heavy: true, risk: 'Fine', longSource: 'iSeeCars',
  };
}

const ROWS = 30;  // more than drawRanked's slice of 24
const ranked = Array.from({ length: ROWS }, (_, i) => fakeRow(i));
/* CR only, not CRLF: this test splits the file on \n to count rows, so a
   quoted LF would break the splitter rather than the export. The escaping of
   all three terminators is asserted directly above. */
ranked[5].risk = 'Runs hot, and the "known" fix is a recall,\rper NHTSA';
ranked[5].name = 'Comma, Motors';

const csv = buildExport(INPUTS, DEFAULTS, FIELDS, AXES, W, 'Custom', 'heavy',
  'Vehicle 0', { href: 'https://example.test/#annual_miles=60000' }, { ranked });
const lines = csv.split('\n');

const headerIdx = lines.findIndex(l => l.startsWith('rank,name,'));
if (headerIdx < 0) throw new Error('no vehicle table header in the export');
const body = lines.slice(headerIdx + 1);

if (body.length !== ROWS) {
  throw new Error(`export carried ${body.length} of ${ROWS} ranked vehicles -- `
    + 'the table is being sliced like the on-screen ranked list. The whole point '
    + 'of the file is looking at all of the data.');
}

/* Every assumption that has no field on the page must still be in the file,
   or the export cannot reproduce the numbers printed beside it. */
for (const label of ['Repair reserve $/mi, over 150k', 'Sales tax rate', 'Loan APR',
  'Industry average 5-year depreciation', 'Cash opportunity rate',
  'Repair cost spread, worst/best']) {
  if (!csv.includes(label)) throw new Error(`export is missing the ${label} assumption`);
}
if (!csv.includes('Annual miles (edited),60000')) {
  throw new Error('an edited assumption is not marked as edited in the export');
}
if (!csv.includes('View,https://example.test/#annual_miles=60000')) {
  throw new Error('the export does not record the view it came from');
}

/* Field counts, parsed for real: an unescaped comma in a risk sentence would
   read as an extra column and silently shift every value after it. */
function fields(line) {
  const out = [];
  let cur = '', quoted = false;
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (quoted) {
      if (c === '"' && line[i + 1] === '"') { cur += '"'; i++; }
      else if (c === '"') quoted = false;
      else cur += c;
    } else if (c === '"') quoted = true;
    else if (c === ',') { out.push(cur); cur = ''; }
    else cur += c;
  }
  out.push(cur);
  return out;
}

const width = fields(lines[headerIdx]).length;
body.forEach((line, i) => {
  const n = fields(line).length;
  if (n !== width) throw new Error(`row ${i + 1} has ${n} fields against ${width} columns`);
});

const nasty = fields(body[5]);
if (nasty[1] !== 'Comma, Motors') throw new Error(`name lost its comma: ${nasty[1]}`);
if (nasty[25] !== 'Runs hot, and the "known" fix is a recall,\rper NHTSA') {
  throw new Error(`risk text did not survive escaping: ${nasty[25]}`);
}

console.log(`ok: export carries ${body.length} vehicles across ${width} columns, `
  + 'assumptions intact');
