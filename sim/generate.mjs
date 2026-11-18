import {once} from 'node:events';
import {createWriteStream, mkdirSync, renameSync, rmSync, writeFileSync} from 'node:fs';
import {dirname, resolve} from 'node:path';
import {parseArgs} from 'node:util';
import {legalActions, loadCatalog, setIndex, simulateBattle} from './battle.mjs';
import {battleFormat, engineCommit} from './engine.mjs';
import {alternateStatPoints, concretizeFoe, createRandom, drawBattleSeed, scenarios} from './scenarios.mjs';

const {values} = parseArgs({
  options: {
    duels: {type: 'string', default: '2400'},
    teams: {type: 'string', default: '2000'},
    trials: {type: 'string', default: '3'},
    seed: {type: 'string', default: '20261118'},
    output: {type: 'string', default: 'data/generated/battles.jsonl'},
    'alternate-sp': {type: 'boolean', default: false},
  },
});

const duels = Number(values.duels);
const teams = Number(values.teams);
const trials = Number(values.trials);
const seed = Number(values.seed);
if (![duels, teams, trials, seed].every(Number.isSafeInteger) ||
    duels < 0 || teams < 0 || duels + teams === 0 || trials < 1 || seed < 1 || seed > 0xffffffff) {
  throw new Error('duels/teams must be nonnegative integers, trials and seed must be positive.');
}

const catalog = loadCatalog();
const species = new Map(catalog.pokemon.map(mon => [mon.id, mon]));
const sets = setIndex(catalog);
const random = createRandom(seed);
const output = resolve(values.output);
mkdirSync(dirname(output), {recursive: true});
const temporary = `${output}.${process.pid}.tmp`;
const stream = createWriteStream(temporary, {flags: 'wx', encoding: 'utf8'});
await once(stream, 'open');

const meta = {
  engine: engineCommit, format: battleFormat, seed, trials, alternate_sp: values['alternate-sp'],
  requested_scenarios: {duel: duels, team: teams},
  records: {duel: 0, team: 0}, ties: {duel: 0, team: 0}, timeouts: {duel: 0, team: 0},
  unavailable: {duel: 0, team: 0},
};
const start = performance.now();
try {
  for (const [mode, count] of [['duel', duels], ['team', teams]]) {
    let index = 0;
    for (const scenario of scenarios(catalog, mode, count, random)) {
      const actions = legalActions(scenario);
      const group = `${seed}:${mode}:${index}`;
      for (let trial = 0; trial < trials; trial += 1) {
        const sampled = concretizeFoe(scenario, species, random);
        const concrete = values['alternate-sp'] ? alternateStatPoints(sampled, sets, random) : sampled;
        const battleSeed = drawBattleSeed(random);
        for (const action of actions) {
          let result;
          try {
            result = simulateBattle(concrete, sets, action, battleSeed);
          } catch (error) {
            console.error(JSON.stringify({group, seed: battleSeed, action, scenario: concrete}));
            throw error;
          }
          if (result === null) {
            meta.timeouts[mode] += 1;
            continue;
          }
          if (result.unavailable) {
            meta.unavailable[mode] += 1;
            continue;
          }
          if (result.win === 0.5) meta.ties[mode] += 1;
          meta.records[mode] += 1;
          if (!stream.write(JSON.stringify({...result, group, seed: battleSeed}) + '\n')) {
            await once(stream, 'drain');
          }
        }
      }
      index += 1;
      if (index % 100 === 0 || index === count) {
        const total = meta.records.duel + meta.records.team;
        const seconds = (performance.now() - start) / 1000;
        console.log(`${mode}: ${index}/${count} scenarios · ${total} battles · ${(total / seconds).toFixed(0)}/s`);
      }
    }
  }
  stream.end();
  await once(stream, 'close');
  renameSync(temporary, output);
  writeFileSync(`${output}.meta.json`, JSON.stringify(meta, null, 2) + '\n');
  console.log(JSON.stringify(meta));
} catch (error) {
  stream.destroy();
  if (!stream.closed) await once(stream, 'close');
  rmSync(temporary, {force: true});
  throw error;
}
