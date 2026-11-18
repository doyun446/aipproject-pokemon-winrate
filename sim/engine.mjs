import {existsSync} from 'node:fs';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';

export const engineCommit = 'f827a1d41064e0dec4c19c6ea0394fcf0c23479c';
export const engineDirectory = fileURLToPath(new URL('../sim-engine/', import.meta.url));
export const battleFormat = 'gen9championsbssregmc';

const require = createRequire(import.meta.url);
const main = fileURLToPath(new URL('../sim-engine/dist/sim/index.js', import.meta.url));

export function loadEngine() {
  if (!existsSync(main)) {
    throw new Error('Showdown 엔진이 필요합니다. npm ci 후 npm run setup:engine을 실행하세요.');
  }
  return require(main);
}
