const {readFileSync, writeFileSync} = require('node:fs');
const path = require('node:path');
const {parseArgs} = require('node:util');

const {values} = parseArgs({options: {'include-fallback': {type: 'boolean'}}});

const stage = path.join(__dirname, '..');
const engine = process.env.SHOWDOWN_ENGINE || path.join(stage, 'sim-engine', 'dist', 'sim');
const {Dex, TeamValidator} = require(engine);
const format = 'gen9championsbssregmc';
const formatName = 'Pokémon Champions · 싱글 레귤레이션 M-C';
const dex = Dex.forFormat(format);
const validator = new TeamValidator(format);

if (dex.currentMod !== 'champions') {
  throw new Error('The Pokémon Showdown engine must include Champions Reg M-C.');
}

const input = path.join(__dirname, 'catalog-input');
const sourceFile = `${format}-1760.json`;
const stats = JSON.parse(readFileSync(path.join(input, sourceFile), 'utf8'));
const statOrder = ['hp', 'atk', 'def', 'spa', 'spd', 'spe'];
const koFormSuffix = {
  Alola: '알로라', Eternal: '영원의꽃', F: '암컷', Galar: '가라르', Hisui: '히스이',
  Heat: '히트', Wash: '워시', Frost: '프로스트', Fan: '스핀', Mow: '커트',
};

function readNames(file) {
  const byNumber = {};
  const byEnglishName = {};
  for (const line of readFileSync(path.join(input, file), 'utf8').split(/\r?\n/)) {
    const match = /^(\d+),(3|9),(?:"((?:[^"]|"")+)"|([^,]+))/.exec(line);
    if (!match) continue;
    const [, number, language, quoted, unquoted] = match;
    const name = quoted ? quoted.replaceAll('""', '"') : unquoted;
    if (language === '3') byNumber[number] = name;
    else byEnglishName[Dex.toID(name)] = number;
  }
  return {byNumber, byEnglishName};
}

const speciesNames = readNames('pokemon_species_names.csv');
const moveNames = readNames('move_names.csv');
const itemNames = readNames('item_names.csv');
const abilityNames = readNames('ability_names.csv');

function speciesNameKo(species) {
  const name = speciesNames.byNumber[species.num] || species.baseSpecies;
  if (species.forme.startsWith('Mega')) return `메가${name}${species.forme.slice(4).replace('-', '')}`;
  if (!species.forme && ['basculegion', 'indeedee'].includes(species.id)) return `${name} (수컷)`;
  const suffix = koFormSuffix[species.forme];
  return suffix ? `${name} (${suffix})` : name;
}

function sorted(entries) {
  return Object.entries(entries).filter(([, count]) => count > 0).sort((a, b) => b[1] - a[1]);
}

function ranked(entries, table, limit = 100) {
  return sorted(entries)
    .filter(([id]) => id === 'nothing' || table.get(id).exists)
    .slice(0, limit)
    .map(([id, count]) => ({name: id === 'nothing' ? '' : table.get(id).name, count}));
}

function proportion(entries, total) {
  return entries.map(({name, count}) => ({name, usage: Math.min(1, count / total)}));
}

function parseSpread(profile) {
  const [nature, distribution] = profile.split(':');
  if (!distribution || !dex.natures.get(nature).exists) return null;
  const points = distribution.split('/').map(Number);
  if (points.length !== 6 || points.some(value => !Number.isInteger(value) || value < 0 || value > 32) ||
      points.reduce((total, value) => total + value) > 66) return null;
  return {nature, evs: Object.fromEntries(statOrder.map((key, index) => [key, points[index]]))};
}

function translation(dictionary, entry) {
  const number = dictionary.byEnglishName[entry.id];
  return dictionary.byNumber[number ?? (dictionary === itemNames ? null : entry.num)];
}

const targetSpeciesCount = 60;
const fallbackSpeciesCount = 12;

function rankBaseSpecies(entries) {
  const groups = new Map();
  for (const [name, usage] of Object.entries(entries)) {
    const species = dex.species.get(name);
    if (!species.exists || usage.usage <= 0) continue;
    const base = dex.species.get(species.baseSpecies);
    if (!groups.has(base.id)) groups.set(base.id, {base, usage: 0, forms: []});
    const group = groups.get(base.id);
    group.usage += usage.usage;
    group.forms.push({name, usage});
  }
  return [...groups.values()].sort((a, b) => b.usage - a.usage);
}

class UnsupportedFormError extends Error {}

function remember(entries, table, names, labels) {
  for (const {name} of entries) {
    if (!name) continue;
    const entry = table.get(name);
    const translated = translation(names, entry);
    if (translated) labels[entry.id] = translated;
  }
}

function legal(set) {
  return !validator.validateSet(structuredClone(set), {});
}

function pokemonEntry(name, usage, {moveNamesKo, itemNamesKo, abilityNamesKo, moveData}) {
  const species = dex.species.get(name);
  if (!species.exists) throw new Error(`Unknown ranked Pokémon ${name}`);
  const mega = species.forme.startsWith('Mega');
  const starting = mega ? species.battleOnly || species.baseSpecies : species.name;
  const base = dex.species.get(Array.isArray(starting) ? starting[0] : starting);
  const possibleAbilities = Object.values(base.abilities);
  const usedAbilities = ranked(usage.Abilities, dex.abilities);
  const abilities = mega ? [possibleAbilities[0]] : usedAbilities.map(entry => entry.name)
    .filter(ability => possibleAbilities.includes(ability));
  const usedItems = ranked(usage.Items, dex.items);
  const availableItems = mega ? usedItems.filter(item => item.name === species.requiredItem) : usedItems;
  const spreads = sorted(usage.Spreads).map(([profile, count]) => ({...parseSpread(profile), count}))
    .filter(profile => profile.nature);
  const moves = ranked(usage.Moves, dex.moves, 36);
  const total = Object.values(usage.Abilities).reduce((sum, count) => sum + count, 0);
  const first = availableItems[0];
  const defaultAbility = abilities[0] || possibleAbilities[0];
  if (!first || !spreads.length || !defaultAbility) throw new UnsupportedFormError(`Missing profile source for ${name}`);
  const test = {
    species: base.name, item: first.name, ability: defaultAbility, level: 50,
    nature: spreads[0].nature, evs: spreads[0].evs,
  };
  const supportedMoves = moves.filter(move => legal({...test, moves: [move.name]}));
  if (supportedMoves.length < 4) throw new UnsupportedFormError(`Fewer than four valid moves for ${name}: ${JSON.stringify(test)}`);

  const profiles = [];
  const diverseItems = availableItems.filter(item => item.count / total >= 0.01).slice(0, 3);
  const candidates = diverseItems.length >= 2 ? diverseItems.map((item, offset) => ({
    item, spread: spreads[Math.min(offset, spreads.length - 1)], offset, count: item.count,
  })) : spreads.slice(0, 3).map((spread, offset) => ({item: first, spread, offset, count: spread.count}));

  for (const candidate of candidates) {
    const item = candidate.item.name;
    const restricted = item.startsWith('Choice ') || item === 'Assault Vest';
    const eligible = supportedMoves.filter(({name: move}) => !restricted ||
      dex.moves.get(move).category !== 'Status' || ['Trick', 'Switcheroo'].includes(move));
    const pool = eligible.length >= 4 ? eligible : supportedMoves;
    const picks = pool.slice(0, 4);
    if (!restricted && pool[4] && candidate.offset > 0) {
      picks[3] = pool[Math.min(3 + candidate.offset, pool.length - 1)];
    }
    const sample = {...test, item, nature: candidate.spread.nature, evs: candidate.spread.evs,
      moves: picks.map(move => move.name)};
    if (!legal(sample)) continue;
    profiles.push({...sample, count: candidate.count});
  }
  if (profiles.length < 2) {
    throw new UnsupportedFormError(`Unable to produce two valid sets for ${name}: ${JSON.stringify(test)}`);
  }

  const mass = profiles.reduce((sum, profile) => sum + profile.count, 0);
  const sets = profiles.map(({count, ...profile}, offset) => ({
    id: `set${offset + 1}`,
    name: `대표 세트 ${offset + 1}`,
    weight: count / mass,
    ...profile,
    mega: mega ? species.name : null,
    battle_ability: mega ? species.abilities['0'] : profile.ability,
  }));
  remember(usedItems.slice(0, 6), dex.items, itemNames, itemNamesKo);
  remember(sets.map(set => ({name: set.ability})), dex.abilities, abilityNames, abilityNamesKo);
  remember(usedAbilities, dex.abilities, abilityNames, abilityNamesKo);
  const shownMoves = [...moves.slice(0, 8), ...sets.flatMap(set => set.moves.map(name => ({name})))];
  remember(shownMoves, dex.moves, moveNames, moveNamesKo);
  for (const {name: moveName} of shownMoves) {
    const entry = dex.moves.get(moveName);
    moveData[entry.name] = {
      type: entry.type, category: entry.category, base_power: entry.basePower,
      priority: entry.priority, accuracy: entry.accuracy === true ? 100 : entry.accuracy,
    };
  }

  return {
    id: species.id, name: species.name, name_ko: speciesNameKo(species),
    base_species: Dex.toID(species.baseSpecies), base_stats: species.baseStats,
    types: species.types, mega, usage: usage.usage, sets,
    item_usage: proportion(usedItems.slice(0, 5), total),
    ability_usage: proportion(usedAbilities.slice(0, 5), total),
    move_usage: proportion(moves.slice(0, 8), total),
  };
}

function selectSpecies(groups, count, {speciesOffset = 0, formOffset = 0} = {}) {
  const pokemon = [];
  const omittedForms = [];
  const metadata = {moveNamesKo: {}, itemNamesKo: {}, abilityNamesKo: {}, moveData: {}};
  let groupsRead = 0;
  let selectedSpecies = 0;
  for (const group of groups) {
    if (selectedSpecies === count) break;
    groupsRead += 1;
    const forms = group.forms.sort((a, b) => b.usage.usage - a.usage.usage).flatMap(({name, usage}) => {
      try {
        return [pokemonEntry(name, usage, metadata)];
      } catch (error) {
        if (!(error instanceof UnsupportedFormError)) throw error;
        omittedForms.push(name);
        console.warn(error.message);
        return [];
      }
    });
    if (!forms.length) continue;
    selectedSpecies += 1;
    const baseNameKo = speciesNames.byNumber[group.base.num] || group.base.name;
    for (const form of forms) {
      pokemon.push({...form, rank: formOffset + pokemon.length + 1, base_name_ko: baseNameKo,
        species_rank: speciesOffset + selectedSpecies, species_usage: group.usage});
    }
  }
  if (selectedSpecies !== count) {
    throw new Error('The source does not contain enough base species with representative sets.');
  }
  return {pokemon, omittedForms, selectedSpecies, groupsRead, ...metadata};
}

const rankedSpecies = rankBaseSpecies(stats.data);
const usageMass = rankedSpecies.reduce((sum, group) => sum + group.usage, 0);

function writeCatalog(filename, selection, extraSource = {}) {
  const {pokemon, omittedForms, selectedSpecies, moveData, moveNamesKo, itemNamesKo, abilityNamesKo} = selection;
  const selectedUsageMass = pokemon.reduce((sum, form) => sum + form.usage, 0);
  const catalog = {
    format,
    format_name: formatName,
    source: {
      month: '2026-10', rating: 1760, battles: stats.info['number of battles'],
      species_count: selectedSpecies, form_count: pokemon.length, usage_coverage: selectedUsageMass / usageMass,
      unsupported_forms: omittedForms,
      usage_url: `https://www.smogon.com/stats/2026-10/${format}-1760.txt`,
      movesets_url: `https://www.smogon.com/stats/2026-10/chaos/${sourceFile}`,
      rules_url: 'https://news.pokemon-home.com/ko/page/816.html',
      prior_method: '도구가 다양한 경우 도구 사용률, 도구가 고정된 경우 능력치 배분 사용률을 대표 세트 안에서 정규화한 추정치입니다. 도구·특성·기술의 개별 사용률은 Showdown 통계입니다.',
      names_url: 'https://github.com/PokeAPI/pokeapi/tree/4e84512eaf7f58a5a50d2a27941b1191cdb9e5e9/data/v2/csv',
      ...extraSource,
    },
    pokemon, move_data: moveData, move_names_ko: moveNamesKo,
    item_names_ko: itemNamesKo, ability_names_ko: abilityNamesKo,
  };
  writeFileSync(path.join(__dirname, filename), `${JSON.stringify(catalog, null, 2)}\n`);
  const setCount = pokemon.reduce((sum, entry) => sum + entry.sets.length, 0);
  console.log(`${filename}: ${selectedSpecies} base species, ${pokemon.length} forms, ${setCount} representative sets`);
}

const training = selectSpecies(rankedSpecies, targetSpeciesCount);
writeCatalog('catalog.json', training);
if (values['include-fallback']) {
  const fallback = selectSpecies(rankedSpecies.slice(training.groupsRead), fallbackSpeciesCount, {
    speciesOffset: training.selectedSpecies,
    formOffset: training.pokemon.length,
  });
  writeCatalog('fallback_catalog.json', fallback, {inference_only: true});
}
