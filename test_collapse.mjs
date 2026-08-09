/* Pins issue #27: the frontier must be computed across every trim BEFORE
   collapsing to one dot per nameplate.

   Extracts the shipped collapseByNameplate and the frontier block straight
   out of index.html rather than reimplementing them, so this fails if the
   page's own logic regresses -- reimplementing would only test the copy. */
import { readFileSync } from 'node:fs';

const html = readFileSync('./index.html', 'utf8');

function extract(pattern, label) {
  const m = html.match(pattern);
  if (!m) throw new Error(`could not find ${label} in index.html -- the test is stale, fix it rather than deleting it`);
  return m[0];
}

const collapseSrc = extract(/function collapseByNameplate\(list,undominated\)\{[\s\S]*?\n\}/, 'collapseByNameplate');
const frontierSrc = extract(/var undominated=\{\};[\s\S]*?if\(!beaten\)undominated\[a\.key\]=1;\s*\}\);/, 'the frontier block');

const collapseByNameplate = new Function(`${collapseSrc}; return collapseByNameplate;`)();
const frontierOf = new Function('scored', `${frontierSrc}; return undominated;`);

// The counterexample from #27, using the page's own field names.
const scored = [
  { key: 'Highlander|base',   name: 'Highlander', cost: 90, value: 50, total: 60 },
  { key: 'Highlander|loaded', name: 'Highlander', cost: 70, value: 62, total: 63 },
  { key: 'Other|unspecified', name: 'Other',      cost: 75, value: 45, total: 52 },
];

const undominated = frontierOf(scored);
const collapsed = collapseByNameplate(scored, undominated);
const winners = collapsed.filter(m => m.onFront).map(m => m.name).sort();

if (!undominated['Highlander|base']) {
  throw new Error('the cheapest undominated trim was dropped from the frontier -- '
    + 'the frontier is being computed after the collapse again (#27)');
}
if (undominated['Other|unspecified']) {
  throw new Error('a vehicle beaten on both axes by a hidden trim was promoted onto '
    + 'the frontier -- the frontier is being computed after the collapse again (#27)');
}
if (JSON.stringify(winners) !== JSON.stringify(['Highlander'])) {
  throw new Error(`expected only Highlander on the frontier, got ${JSON.stringify(winners)}`);
}

const rep = collapsed.find(m => m.name === 'Highlander');
if (!undominated[rep.key]) {
  throw new Error(`the representative ${rep.key} is a dominated trim; an undominated one exists`);
}
if (collapsed.length !== 2) {
  throw new Error(`expected 2 dots for 2 nameplates, got ${collapsed.length}`);
}

/* The checks above prove the two pieces behave correctly when composed in the
   right order -- but this test composes them, so it cannot see whether the
   PAGE does. These assertions read the wiring itself. */
const computeSrc = extract(/function compute\(\)\{[\s\S]*?return \{scored:collapsed[^}]*\};/, 'compute()');

const iFrontier = computeSrc.indexOf('var undominated={}');
const iCollapse = computeSrc.indexOf('collapseByNameplate(scored');
if (iFrontier < 0 || iCollapse < 0) {
  throw new Error('compute() no longer computes undominated before calling collapseByNameplate(scored, ...) -- #27');
}
if (iFrontier > iCollapse) {
  throw new Error('compute() collapses before computing the frontier -- that is the #27 defect');
}
if (!/collapseByNameplate\(scored,\s*undominated\)/.test(computeSrc)) {
  throw new Error('collapseByNameplate is not being given the full scored list plus the frontier set -- #27');
}
if (!/var front=collapsed\.filter\(function\(m\)\{return m\.onFront\}\)/.test(computeSrc)) {
  throw new Error('front is no longer derived from onFront; it is being recomputed over the collapsed list -- #27');
}

console.log('ok: frontier computed across all trims, then collapsed, and compute() wires it that way (#27)');
