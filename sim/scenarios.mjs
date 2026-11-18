export function createRandom(seed) {
  let state = seed >>> 0 || 0x85ebca6b;
  return () => {
    state ^= state << 13;
    state ^= state >>> 17;
    state ^= state << 5;
    return (state >>> 0) / 0x100000000;
  };
}

export function drawBattleSeed(random) {
  return Array.from({length: 4}, () => Math.floor(random() * 65536)).join(',');
}

function pick(choices, random) {
  return choices[Math.floor(random() * choices.length)];
}

function weighted(choices, random, weight = choice => choice.weight) {
  const total = choices.reduce((sum, choice) => sum + weight(choice), 0);
  let ticket = random() * total;
  for (const choice of choices) {
    ticket -= weight(choice);
    if (ticket < 0) return choice;
  }
  return choices.at(-1);
}

function showdownId(name = '') {
  return (name || '').toLowerCase().replace(/[^a-z0-9]+/g, '');
}

export function concretizeFoe(scenario, species, random) {
  const candidates = scenario.foe.map(card => {
    const mon = species.get(card.pokemon);
    if (!mon) throw new Error(`Unknown Pokémon: ${card.pokemon}`);
    const revealedItem = showdownId(card.revealed_item);
    const revealedMoves = (card.revealed_moves || []).filter(Boolean).map(showdownId);
    const compatible = mon.sets.filter(set =>
      (!card.set || set.id === card.set) &&
      (!revealedItem || showdownId(set.item) === revealedItem) &&
      revealedMoves.every(move => set.moves.some(name => showdownId(name) === move))
    );
    if (!compatible.length) throw new Error(`No compatible opponent set: ${card.pokemon}`);
    return compatible;
  });
  const combinations = [];
  function collect(slot, sets, used, weight) {
    if (slot >= candidates.length) {
      combinations.push({sets, weight});
      return;
    }
    for (const set of candidates[slot]) {
      const item = showdownId(set.item);
      if (item && used.has(item)) continue;
      const nextUsed = new Set(used);
      if (item) nextUsed.add(item);
      collect(slot + 1, [...sets, set.id], nextUsed, weight * set.weight);
    }
  }
  collect(0, [], new Set(), 1);
  const combination = weighted(combinations, random);
  if (!combination) throw new Error('No opponent sets satisfy Item Clause.');
  return {
    ...scenario,
    foe: scenario.foe.map((card, index) => ({...card, set: combination.sets[index]})),
  };
}

function sweepPairs(pokemon, random) {
  const pairs = [];
  for (let i = 0; i < pokemon.length; i += 1) {
    for (let j = i; j < pokemon.length; j += 1) {
      pairs.push([pokemon[i], pokemon[j]]);
    }
  }
  for (let i = pairs.length - 1; i > 0; i -= 1) {
    const other = Math.floor(random() * (i + 1));
    [pairs[i], pairs[other]] = [pairs[other], pairs[i]];
  }
  return pairs;
}

function activeState(random) {
  const status = random() < 0.73 ? '' : pick(['brn', 'par', 'psn', 'tox', 'slp', 'frz'], random);
  return {
    hp: random() < 0.31 ? 100 : 10 + Math.floor(random() * 90),
    status,
    attack: random() < 0.76 ? 0 : pick([-2, -1, 1, 2, 3], random),
    speed: random() < 0.78 ? 0 : pick([-2, -1, 1, 2, 3], random),
  };
}

function benchState(random) {
  return {
    hp: random() < 0.52 ? 100 : 20 + Math.floor(random() * 80),
    status: '',
    attack: 0,
    speed: 0,
  };
}

export function alternateStatPoints(scenario, sets, random) {
  const change = card => {
    const set = sets.get(`${card.pokemon}/${card.set}`);
    const evs = {...set.evs};
    const names = Object.keys(evs);
    const source = pick(names.filter(stat => evs[stat] >= 2), random);
    const target = pick(names.filter(stat => stat !== source && evs[stat] <= 30), random);
    const capacity = Math.min(8, evs[source], 32 - evs[target]);
    const step = 2 + Math.floor(random() * (capacity - 1));
    evs[source] -= step;
    evs[target] += step;
    return {...card, evs};
  };
  return {...scenario, own: scenario.own.map(change), foe: scenario.foe.map(change)};
}

function makeSide(pokemon, lead, length, random, hidden) {
  const firstSet = weighted(lead.sets, random);
  const used = new Set([showdownId(firstSet.item)]);
  const side = [{pokemon: lead.id, set: hidden ? '' : firstSet.id, ...activeState(random)}];
  const baseSpecies = new Set([lead.base_species]);
  let mega = lead.mega;
  while (side.length < length) {
    const choices = pokemon.filter(mon => !baseSpecies.has(mon.base_species) && (!mega || !mon.mega));
    const legal = choices.map(mon => ({
      mon,
      sets: mon.sets.filter(set => !set.item || !used.has(showdownId(set.item))),
    })).filter(entry => entry.sets.length);
    const {mon, sets} = pick(legal, random);
    const set = weighted(sets, random);
    side.push({pokemon: mon.id, set: hidden ? '' : set.id, ...benchState(random)});
    baseSpecies.add(mon.base_species);
    used.add(showdownId(set.item));
    mega ||= mon.mega;
  }
  return side;
}

export function* scenarios(catalog, mode, count, random) {
  const size = mode === 'duel' ? 1 : 3;
  const pokemon = catalog.pokemon;
  let pairs = [];
  for (let index = 0; index < count; index += 1) {
    if (!pairs.length) pairs = sweepPairs(pokemon, random);
    const pair = pairs.pop();
    if (random() < 0.5) pair.reverse();
    yield {
      mode,
      own: makeSide(pokemon, pair[0], size, random, false),
      foe: makeSide(pokemon, pair[1], size, random, true),
      weather: random() < 0.72 ? '' : pick(['rain', 'sun', 'sand', 'snow'], random),
    };
  }
}
