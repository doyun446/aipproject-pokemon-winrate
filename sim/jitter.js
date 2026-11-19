// 능력 포인트(SP) 흔들기 — 규칙은 data/sets60_v2.json 의 meta.sp_jitter 참고
// 사용 예:
//   const {makeRng, jitterSP} = require('./jitter');
//   const rng = makeRng(baseSeed, gameId, side);      // side: 0 = p1, 1 = p2
//   const {sp, jittered, moved} = jitterSP(set.sp, rng);
//   // 엔진에 넣을 때: evs = sp (챔피언스 규칙은 능력 포인트를 evs 칸에 그대로 사용)
'use strict';
const STATS = ['hp', 'atk', 'def', 'spa', 'spd', 'spe'];
const RULE = {keepProb: 0.3, minMove: 1, maxMove: 4, maxStat: 32, maxTotal: 66};

// 재현 가능한 난수 (mulberry32)
function mulberry32(a) {
  return function () {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
// (기본 시드, 판 번호, 쪽) → 난수 생성기
function makeRng(baseSeed, gameId, side) {
  let h = 2166136261;
  for (const v of [baseSeed, gameId, side]) {
    h ^= (v >>> 0); h = Math.imul(h, 16777619);
  }
  return mulberry32(h >>> 0);
}

function jitterSP(baseSp, rng, rule = RULE) {
  const sp = {...baseSp};
  if (rng() < rule.keepProb) return {sp, jittered: false, moved: 0};
  const n = rule.minMove + Math.floor(rng() * (rule.maxMove - rule.minMove + 1));
  let moved = 0;
  for (let i = 0; i < n; i++) {
    // 주는 쪽: 0보다 큰 능력치, 값에 비례한 확률
    const donors = STATS.filter(k => sp[k] > 0);
    const total = donors.reduce((s, k) => s + sp[k], 0);
    if (total === 0) break;
    let r = rng() * total, donor = donors[donors.length - 1];
    for (const k of donors) { r -= sp[k]; if (r < 0) { donor = k; break; } }
    // 받는 쪽: 32보다 작은 다른 능력치, 균등
    const recv = STATS.filter(k => k !== donor && sp[k] < rule.maxStat);
    if (recv.length === 0) break;
    const to = recv[Math.floor(rng() * recv.length)];
    sp[donor] -= 1; sp[to] += 1; moved += 1;
  }
  return {sp, jittered: moved > 0, moved};
}

function isValidSP(sp, rule = RULE) {
  const vals = STATS.map(k => sp[k]);
  return vals.every(v => Number.isInteger(v) && v >= 0 && v <= rule.maxStat) &&
         vals.reduce((a, b) => a + b, 0) <= rule.maxTotal;
}

module.exports = {STATS, RULE, makeRng, jitterSP, isValidSP};
