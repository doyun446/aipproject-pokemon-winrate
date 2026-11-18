import {execFileSync} from 'node:child_process';
import {existsSync, mkdirSync, readdirSync} from 'node:fs';
import {resolve} from 'node:path';
import {battleFormat, engineCommit, engineDirectory, loadEngine} from './engine.mjs';

const upstream = 'https://github.com/smogon/pokemon-showdown.git';

function git(args, options = {}) {
  return execFileSync('git', ['-C', engineDirectory, ...args], {stdio: 'inherit', ...options});
}

mkdirSync(engineDirectory, {recursive: true});
if (!existsSync(resolve(engineDirectory, '.git'))) {
  if (readdirSync(engineDirectory).length) {
    throw new Error('sim-engine이 비어 있는 폴더가 아닙니다.');
  }
  git(['init']);
}

let current;
try {
  current = git(['rev-parse', '--verify', 'HEAD'], {encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore']}).trim();
} catch {
  git(['fetch', '--depth=1', upstream, engineCommit]);
  git(['checkout', '--detach', engineCommit]);
}

if (current && current !== engineCommit) {
  throw new Error(`sim-engine의 버전을 확인하세요. 필요한 버전은 ${engineCommit}입니다.`);
}

execFileSync(process.execPath, ['build'], {cwd: engineDirectory, stdio: 'inherit'});
const {Dex} = loadEngine();
if (Dex.formats.get(battleFormat).mod !== 'champions') {
  throw new Error('챔피언스 싱글 포맷을 불러오지 못했습니다.');
}
console.log(`Pokémon Showdown ${engineCommit.slice(0, 12)} · ${battleFormat}`);
