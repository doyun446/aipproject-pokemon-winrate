import {readFileSync} from 'node:fs';
import {battleFormat, loadEngine} from './engine.mjs';

const weatherConditions = {
  rain: 'raindance',
  sun: 'sunnyday',
  sand: 'sandstorm',
  snow: 'snowscape',
};

const formatByMode = {
  duel: `${battleFormat}@@@!! Min Team Size = 1,!! Picked Team Size = 1`,
  team: `${battleFormat}@@@!! Min Team Size = 3`,
};

const healingMoves = new Set([
  'recover', 'roost', 'slackoff', 'softboiled', 'synthesis', 'morningsun',
  'moonlight', 'strengthsap', 'shoreup', 'milkdrink', 'lifedew',
]);

export function loadCatalog(path = new URL('../data/catalog.json', import.meta.url)) {
  return JSON.parse(readFileSync(path, 'utf8').replace(/^\uFEFF/, ''));
}

export function setIndex(catalog) {
  return new Map(catalog.pokemon.flatMap(mon =>
    mon.sets.map(set => [`${mon.id}/${set.id}`, set])
  ));
}

export function showdownSet(set) {
  return {
    name: set.species,
    species: set.species,
    ability: set.ability,
    item: set.item,
    moves: set.moves.slice(),
    nature: set.nature,
    evs: {...set.evs},
    ivs: {hp: 31, atk: 31, def: 31, spa: 31, spd: 31, spe: 31},
    level: 50,
    gender: set.gender || '',
  };
}

const statNames = ['hp', 'atk', 'def', 'spa', 'spd', 'spe'];

function withStatPoints(set, override) {
  if (!override) return set;
  const evs = {...set.evs, ...override};
  if (Object.keys(override).some(stat => !statNames.includes(stat)) ||
      Object.values(evs).some(value => !Number.isInteger(value) || value < 0 || value > 32) ||
      Object.values(evs).reduce((total, value) => total + value, 0) > 66) {
    throw new Error('Invalid Champions Stat Point allocation.');
  }
  return {...set, evs};
}

export function legalActions(scenario) {
  return scenario.mode === 'duel' ? ['auto'] : [
    'move:0', 'move:1', 'move:2', 'move:3',
    ...scenario.own.slice(1).map((_, i) => `switch:${i + 1}`),
  ];
}

function changeBenchOrActiveHp(pokemon, percent) {
  if (!Number.isFinite(percent) || percent < 1 || percent > 100) {
    throw new Error(`Invalid living HP percentage: ${percent}`);
  }
  pokemon.sethp(Math.max(1, Math.round(pokemon.maxhp * percent / 100)));
}

function initializeBattle(scenario, sets, seed) {
  const {Battle} = loadEngine();
  const resolve = card => {
    const set = sets.get(`${card.pokemon}/${card.set}`);
    if (!set) throw new Error(`Unknown set ${card.pokemon}/${card.set}`);
    return withStatPoints(set, card.evs);
  };
  const ownSets = scenario.own.map(resolve);
  const foeSets = scenario.foe.map(resolve);
  const battle = new Battle({
    formatid: formatByMode[scenario.mode],
    seed,
    strictChoices: true,
    p1: {name: 'own', team: ownSets.map(showdownSet)},
    p2: {name: 'foe', team: foeSets.map(showdownSet)},
  });
  battle.makeChoices(...[ownSets, foeSets].map(team => `team ${team.map((_, i) => i + 1).join('')}`));

  const effective = structuredClone(scenario);
  for (const [index, cards] of [effective.own, effective.foe].entries()) {
    const side = battle.sides[index];
    const active = side.active[0];
    const activeSet = (index === 0 ? ownSets : foeSets)[0];
    // The selected active form is visible now. A benched stone holder evolves
    // on its next selected move after entry, following the simulator's order.
    if (activeSet.mega && active.canMegaEvo === activeSet.mega) {
      battle.actions.runMegaEvo(active);
    }
    for (const [i, card] of cards.entries()) changeBenchOrActiveHp(side.pokemon[i], card.hp);
    active.setBoost({atk: cards[0].attack, spe: cards[0].speed});
  }

  battle.field.clearWeather();
  if (effective.weather) battle.field.setWeather(weatherConditions[effective.weather], 'debug');

  for (const [index, cards] of [effective.own, effective.foe].entries()) {
    const active = battle.sides[index].active[0];
    const card = cards[0];
    if (card.status) {
      active.setStatus(card.status, battle.sides[1 - index].active[0]);
      card.status = active.status;
    }
  }
  for (const active of battle.getAllActive()) {
    active.trapped = active.maybeTrapped = false;
    battle.runEvent('TrapPokemon', active);
  }
  battle.makeRequest('move');
  return {battle, effective};
}

function estimateDamage(battle, attacker, target, move) {
  if (move.category === 'Status' || !target?.hp) return 0;
  if (!battle.dex.getImmunity(move, target)) return 0;
  if (move.type === 'Ground' && !target.isGrounded()) return 0;
  const damage = move.damage === 'level' ? attacker.level : move.damage;
  if (Number.isFinite(damage)) return damage;

  const physical = move.category === 'Physical';
  const off = attacker.getStat(move.overrideOffensiveStat || (physical ? 'atk' : 'spa'), false, true);
  const def = target.getStat(move.overrideDefensiveStat || (physical ? 'def' : 'spd'), false, true);
  const stab = attacker.hasType(move.type) ? 1.5 : 1;
  const effectiveness = 2 ** battle.dex.getEffectiveness(move, target);
  const accuracy = move.accuracy === true ? 1 : move.accuracy / 100;
  const burn = physical && attacker.status === 'brn' && !attacker.hasAbility('guts') ? 0.5 : 1;
  const hits = Array.isArray(move.multihit) ? 3 : move.multihit || 1;
  const base = move.basePower || (move.basePowerCallback ? 75 : 0);

  let weather = 1;
  const currentWeather = battle.field.effectiveWeather();
  if (['raindance', 'sunnyday'].includes(currentWeather) && ['Fire', 'Water'].includes(move.type)) {
    weather = (currentWeather === 'raindance') === (move.type === 'Water') ? 1.5 : 0.5;
  }
  if (base === 0) return 0;
  return (((2 * attacker.level / 5 + 2) * base * off / def) / 50 + 2)
    * stab * effectiveness * accuracy * burn * hits * weather * 0.925;
}

function moveValue(battle, attacker, target, move, moveSlot) {
  const damage = estimateDamage(battle, attacker, target, move);
  if (damage > 0) {
    const ko = damage >= target.hp ? 0.65 + Math.max(0, move.priority) * 0.25 : 0;
    const recoil = move.recoil && attacker.hp < attacker.maxhp * 0.3 ? 0.15 : 0;
    return Math.min(1, damage / target.hp) + ko - recoil;
  }
  if (move.category !== 'Status') return -0.01;
  const hpFraction = attacker.hp / attacker.maxhp;
  if (healingMoves.has(move.id) && hpFraction <= 0.45 && moveSlot.pp > 1) {
    return 0.32;
  }
  if (move.status && !target.status && battle.dex.getImmunity(move.status, target)) {
    return 0.21;
  }
  if (move.boosts && move.target === 'self' && hpFraction > 0.65) {
    const raisesAttack = ['atk', 'spa', 'spe'].some(name => move.boosts[name] > 0 && attacker.boosts[name] < 2);
    if (raisesAttack) return 0.35;
  }
  return -0.02;
}

function choiceMove(battle, side) {
  const actor = side.active[0];
  const target = side.foe.active[0];
  const choices = side.activeRequest.active[0].moves;
  let best = null;
  for (const [index, slot] of choices.entries()) {
    if (slot.disabled) continue;
    const value = moveValue(battle, actor, target, battle.dex.moves.get(slot.id), slot);
    if (!best || value > best.value) best = {index, value};
  }
  if (!best) return 'auto';
  const mega = side.activeRequest.active[0].canMegaEvo ? ' mega' : '';
  return `move ${best.index + 1}${mega}`;
}

function choiceSwitch(battle, side) {
  if (side.slotConditions[side.active[0].position].revivalblessing) {
    const target = side.pokemon.findIndex(pokemon => pokemon.fainted);
    return target >= 0 ? `switch ${target + 1}` : 'auto';
  }
  const target = side.foe.active[0];
  let best = null;
  for (const [index, candidate] of side.pokemon.entries()) {
    if (candidate.isActive || candidate.fainted || !candidate.hp) continue;
    const offense = Math.max(0, ...candidate.moves.map(id => estimateDamage(battle, candidate, target, battle.dex.moves.get(id))));
    const value = offense / Math.max(1, target?.maxhp || 1) + candidate.hp / candidate.maxhp * 0.2;
    if (!best || value > best.value) best = {index, value};
  }
  return best ? `switch ${best.index + 1}` : 'auto';
}

function policy(battle, side) {
  switch (side.requestState) {
  case 'move':
    return choiceMove(battle, side);
  case 'switch':
    return choiceSwitch(battle, side);
  default:
    return '';
  }
}

function firstChoice(battle, action) {
  const side = battle.sides[0];
  const [kind, index] = action.split(':');
  if (kind === 'auto') return choiceMove(battle, side);
  if (kind === 'switch') return `switch ${Number(index) + 1}`;
  const mega = side.activeRequest.active[0].canMegaEvo ? ' mega' : '';
  return `move ${Number(index) + 1}${mega}`;
}

function advance(battle, override) {
  const choices = battle.sides.map((side, i) => i === 0 && override ? override : policy(battle, side));
  if (!choices.some(Boolean)) throw new Error('Battle started a step without any required choices.');
  for (const [i, choice] of choices.entries()) {
    if (choice) battle.choose(battle.sides[i].id, choice);
  }
}

export function simulateBattle(scenario, sets, action, seed) {
  const {battle, effective} = initializeBattle(scenario, sets, seed);
  const isSwitch = action.startsWith('switch:');
  if (isSwitch && battle.sides[0].active[0].trapped) return {unavailable: true};
  const actorIndex = isSwitch ? Number(action.split(':')[1]) : 0;
  const actor = battle.sides[0].pokemon[actorIndex];
  const initialTurn = battle.turn;
  advance(battle, firstChoice(battle, action));

  let hpAfter;
  for (let steps = 1; steps <= 400; steps += 1) {
    if (hpAfter === undefined && (battle.ended || battle.turn > initialTurn)) {
      hpAfter = Math.max(0, Math.round(100 * actor.hp / actor.maxhp * 10) / 10);
    }
    if (battle.ended) {
      const win = battle.winner === 'own' ? 1 : battle.winner === 'foe' ? 0 : 0.5;
      return {scenario: effective, action, win, hp_after: hpAfter, turns: battle.turn};
    }
    advance(battle);
  }
  // The timeout is an unobserved outcome. It must never be labeled a tie.
  return null;
}
