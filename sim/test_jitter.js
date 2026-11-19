// 흔들기 규칙 검사: node sim/test_jitter.js data/sets60_v2.json
'use strict';
const path = require('path');
const {STATS, makeRng, jitterSP, isValidSP} = require('./jitter');
const file = process.argv[2] || path.join(__dirname, '..', 'data', 'sets60_v2.json');
const data = require(path.resolve(file));
const l1 = (a, b) => STATS.reduce((s, k) => s + Math.abs(a[k] - b[k]), 0);
let n = 0, bad = 0, hitEval = 0, keep = 0, maxL1 = 0;
const movedHist = [0, 0, 0, 0, 0];
for (const p of data.pokemon) for (const s of p.sets) {
  for (let g = 0; g < 2000; g++) {
    const {sp, moved} = jitterSP(s.sp, makeRng(42, g, 0));
    n++; movedHist[moved]++; if (moved === 0) keep++;
    if (!isValidSP(sp)) bad++;
    maxL1 = Math.max(maxL1, l1(sp, s.sp));
    // 같은 형태의 평가 배분과 겹치면 안 됨
    for (const t of p.sets) if (t.form === s.form && t.eval_sp && l1(sp, t.eval_sp) === 0) hitEval++;
  }
}
// 재현성: 같은 시드 → 같은 결과
const s0 = data.pokemon[0].sets[0].sp;
const a = jitterSP(s0, makeRng(7, 123, 1)).sp, b = jitterSP(s0, makeRng(7, 123, 1)).sp;
console.log(`표본 ${n}개 | 규칙 위반 ${bad} | 평가 배분과 일치 ${hitEval} | 그대로 둔 비율 ${(keep / n * 100).toFixed(1)}% | 최대 L1 거리 ${maxL1}`);
console.log('옮긴 점수 분포 0~4:', movedHist.map(v => (v / n * 100).toFixed(1) + '%').join(' / '));
console.log('같은 시드 재현:', JSON.stringify(a) === JSON.stringify(b) ? 'OK' : '실패');
