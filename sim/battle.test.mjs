import assert from 'node:assert/strict';
import test from 'node:test';
import {legalActions, loadCatalog, setIndex, simulateBattle} from './battle.mjs';
import {concretizeFoe, createRandom} from './scenarios.mjs';

const catalog = loadCatalog();
const sets = setIndex(catalog);
const seed = '12345,54321,54321,42';

function card(pokemon, hp = 100) {
  return {pokemon, set: 'set1', hp, status: '', attack: 0, speed: 0};
}

test('seeded Champions outcomes and turn HP are replayable', () => {
  const scenario = {
    mode: 'duel',
    own: [{...card('primarina', 67), status: 'par'}],
    foe: [card('garchomp', 45)],
    weather: 'rain',
  };
  assert.deepEqual(legalActions(scenario), ['auto']);
  const result = simulateBattle(scenario, sets, 'auto', seed);
  assert.deepEqual(result, simulateBattle(scenario, sets, 'auto', seed));
  assert.equal(result.scenario.own[0].status, 'par');
  assert.ok([0, 0.5, 1].includes(result.win));
  assert.ok(result.hp_after >= 0 && result.hp_after <= 100);
});

test('an opening switch takes the opposing attack that turn', () => {
  const scenario = {
    mode: 'team',
    own: [card('primarina'), card('garchomp'), card('golisopodmega')],
    foe: [card('gholdengo'), card('archaludon'), card('basculegion')],
    weather: 'rain',
  };
  assert.equal(legalActions(scenario).length, 6);
  const result = simulateBattle(scenario, sets, 'switch:1', seed);
  assert.ok(result.hp_after > 0 && result.hp_after < scenario.own[1].hp);
});

test('Mega Gengar applies Shadow Tag to the chosen opening state', () => {
  const scenario = {
    mode: 'team',
    own: [card('garchomp'), card('corviknight'), card('gholdengo')],
    foe: [card('gengarmega'), card('primarina'), card('meowscarada')],
    weather: '',
  };
  assert.deepEqual(simulateBattle(scenario, sets, 'switch:1', seed), {unavailable: true});
  [scenario.own[0], scenario.own[2]] = [scenario.own[2], scenario.own[0]];
  assert.ok([0, 0.5, 1].includes(simulateBattle(scenario, sets, 'switch:1', seed).win));
});

test('an observed item and move constrain hidden-set rollouts', () => {
  const species = new Map(catalog.pokemon.map(mon => [mon.id, mon]));
  const scenario = {
    mode: 'duel',
    own: [card('garchomp')],
    foe: [{
      ...card('primarina'), set: '', revealed_item: 'Sitrus Berry', revealed_moves: ['Aqua Jet'],
    }],
    weather: '',
  };
  const concrete = concretizeFoe(scenario, species, createRandom(5));
  assert.equal(concrete.foe[0].set, 'set1');
  scenario.foe[0].revealed_moves = ['Flamethrower'];
  assert.throws(() => concretizeFoe(scenario, species, createRandom(5)), /No compatible opponent set/);
});
