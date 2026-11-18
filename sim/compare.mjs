import {readFileSync, writeFileSync} from 'node:fs';
import {parseArgs} from 'node:util';
import {legalActions, loadCatalog, setIndex, simulateBattle} from './battle.mjs';
import {battleFormat, engineCommit} from './engine.mjs';
import {concretizeFoe, createRandom, drawBattleSeed, scenarios} from './scenarios.mjs';

const {values} = parseArgs({
  options: {
    scenario: {type: 'string'},
    'test-split': {type: 'string'},
    'case-seed': {type: 'string', default: '20261202'},
    'case-offset': {type: 'string', default: '0'},
    'case-count': {type: 'string', default: '50'},
    trials: {type: 'string', default: '500'},
    seed: {type: 'string', default: '45281964'},
    output: {type: 'string'},
  },
});

const trials = Number(values.trials);
const seed = Number(values.seed);
if (Boolean(values.scenario) === Boolean(values['test-split']) || !Number.isSafeInteger(trials) || trials <= 0 ||
    !Number.isSafeInteger(seed) || seed <= 0 || seed > 0xffffffff) {
  throw new Error('node sim/compare.mjs --scenario <json> or --test-split <metrics.json> --trials <positive integer>');
}

const catalog = loadCatalog();
const species = new Map(catalog.pokemon.map(mon => [mon.id, mon]));
const sets = setIndex(catalog);
const random = createRandom(seed);
function readJson(path) {
  return JSON.parse(readFileSync(path, 'utf8').replace(/^\uFEFF/, ''));
}

function selectTestCases() {
  const offset = Number(values['case-offset']);
  const count = Number(values['case-count']);
  const caseSeed = Number(values['case-seed']);
  if (![offset, count, caseSeed].every(Number.isSafeInteger) ||
      offset < 0 || count <= 0 || caseSeed <= 0 || caseSeed > 0xffffffff) {
    throw new Error('Invalid test sampling offset, count, or seed.');
  }
  const testPairs = new Set(readJson(values['test-split']).data.matchup_partitions.test);
  const sweepSize = catalog.pokemon.length * (catalog.pokemon.length + 1) / 2;
  const selected = [];
  const seen = new Set();
  for (const scenario of scenarios(catalog, 'duel', sweepSize, createRandom(caseSeed))) {
    const id = [scenario.own[0], scenario.foe[0]].map(card => species.get(card.pokemon).base_species).sort().join('|');
    if (!testPairs.has(id) || seen.has(id)) continue;
    seen.add(id);
    selected.push({id, scenario});
    if (selected.length >= offset + count) break;
  }
  if (selected.length !== offset + count) throw new Error('Test split has too few distinct matchups.');
  return selected.slice(offset);
}

function loadCases() {
  if (values['test-split']) return selectTestCases();
  const input = readJson(values.scenario);
  return Array.isArray(input) ? input : [input.scenario ? input : {scenario: input}];
}

const cases = loadCases();

function summarize(action, row) {
  const winRate = row.n ? row.winSum / row.n : null;
  const hpMean = row.n ? row.hpSum / row.n : null;
  // Tie outcomes count as 0.5, so estimate the variance from the outcomes.
  const variance = row.n > 1 ? Math.max(0, (row.winSquaredSum - row.n * winRate ** 2) / (row.n - 1)) : null;
  const standardError = variance === null ? null : Math.sqrt(variance / row.n);
  return {
    action, n: row.n, ties: row.ties, timeouts: trials - row.n - row.unavailable, unavailable: row.unavailable,
    win_rate: winRate,
    hp_after: hpMean,
    standard_error: standardError,
  };
}

function normalize(raw) {
  const scenario = {
    ...raw,
    own: raw.own.map(card => ({hp: 100, status: '', attack: 0, speed: 0, ...card})),
    foe: raw.foe.map(card => ({hp: 100, status: '', attack: 0, speed: 0, ...card})),
    weather: raw.weather || '',
  };
  if (!['duel', 'team'].includes(scenario.mode)) throw new Error('Scenario mode must be duel or team.');
  const count = scenario.mode === 'duel' ? 1 : 3;
  if (scenario.own.length !== count || scenario.foe.length !== count) {
    throw new Error(`Scenario needs ${count} Pokémon per side.`);
  }
  for (const side of [scenario.own, scenario.foe]) {
    const entries = side.map(card => {
      const mon = species.get(card.pokemon);
      if (!mon) throw new Error(`Unknown Pokémon: ${card.pokemon}`);
      return mon;
    });
    if (new Set(entries.map(mon => mon.base_species)).size !== count || entries.filter(mon => mon.mega).length > 1) {
      throw new Error('Each side needs unique species and at most one Mega Evolution.');
    }
  }
  const ownItems = scenario.own.map(card => {
    const set = sets.get(`${card.pokemon}/${card.set}`);
    if (!set) throw new Error(`Unknown own set ${card.pokemon}/${card.set}`);
    return set.item;
  }).filter(Boolean);
  if (new Set(ownItems).size !== ownItems.length) throw new Error('Own items must satisfy Item Clause.');
  return scenario;
}

const reports = [];
for (const [index, entry] of cases.entries()) {
  const scenario = normalize(entry.scenario);
  const legal = legalActions(scenario);
  const actions = entry.actions || legal;
  if (!actions.length || actions.some(action => !legal.includes(action)) || actions.length !== new Set(actions).size) {
    throw new Error(`Invalid action subset. Allowed actions are ${legal.join(', ')}.`);
  }
  const summary = new Map(actions.map(action => [
    action, {n: 0, ties: 0, unavailable: 0, winSum: 0, winSquaredSum: 0, hpSum: 0},
  ]));
  for (let trial = 0; trial < trials; trial += 1) {
    const concrete = concretizeFoe(scenario, species, random);
    const battleSeed = drawBattleSeed(random);
    for (const action of actions) {
      const result = simulateBattle(concrete, sets, action, battleSeed);
      if (!result) continue;
      const row = summary.get(action);
      if (result.unavailable) {
        row.unavailable += 1;
        continue;
      }
      row.n += 1;
      if (result.win === 0.5) row.ties += 1;
      row.winSum += result.win;
      row.winSquaredSum += result.win ** 2;
      row.hpSum += result.hp_after;
    }
  }
  reports.push({
    id: entry.id || String(index + 1),
    ...(values['test-split'] && {scenario}),
    results: [...summary].map(([action, row]) => summarize(action, row)),
  });
}
const result = JSON.stringify({engine: engineCommit, format: battleFormat, seed, trials, cases: reports}, null, 2) + '\n';
if (values.output) writeFileSync(values.output, result);
else process.stdout.write(result);
