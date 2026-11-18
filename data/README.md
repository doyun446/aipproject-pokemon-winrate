# 포켓몬 및 대표 세트 데이터

`catalog.json`은 Pokémon Showdown의 챔피언스 싱글 레귤레이션 M-C에서 2026년 10월에 기록된 87,848판의 사용률 집계를 바탕으로 만들었습니다. Smogon의 1760 기준 가중 사용률을 기본 종별로 합산한 뒤, 지원 가능한 상위 60마리를 골랐습니다. 메가진화와 지역폼은 같은 종으로 세되 실제 대면에서는 폼마다 다른 타입·능력치·세트를 사용합니다. 카탈로그에 95개 폼과 대표 세트 279개를 담았습니다. [종별 사용률](https://www.smogon.com/stats/2026-10/gen9championsbssregmc-1760.txt) · [도구·특성·기술·능력치 분포](https://www.smogon.com/stats/2026-10/chaos/gen9championsbssregmc-1760.json) · [공식 레귤레이션](https://news.pokemon-home.com/ko/page/816.html)

- 전체 가중 사용률 합에서 카탈로그의 95개 폼이 차지하는 비율은 91.39%입니다. `species_usage`는 같은 종의 폼을 합산한 사용률이고, `usage`는 개별 폼의 사용률입니다.
- 메타몽은 변신으로 기술 슬롯이 바뀌어 네 기술을 고정하는 현재 시뮬레이션 방식에서는 제외했습니다. 다음 순위인 라우드본을 포함했습니다.
- `item_usage`, `ability_usage`, `move_usage`는 각 항목의 개별 가중 사용률입니다. 기술을 네 개까지 채택할 수 있으므로 기술별 사용률의 합은 100%를 넘을 수 있습니다.
- `sets`는 자주 등장한 기술, 도구, 특성과 능력치 배분을 조합한 대표 구성입니다. 집계에 세트 전체의 동시 채택 빈도가 없으므로, 여러 도구를 쓰는 종은 도구 상위 분포를 사용하고 도구가 한 종류인 경우 능력치 배분 상위 분포를 사용해 대표 구성끼리 가중치(`weight`)의 합이 1이 되도록 계산합니다. 추정에는 메타 통계에 공개된 항목별 사용률을 사용합니다.
- `evs`는 Showdown의 필드 이름이며 각 능력치의 챔피언스 스탯 포인트를 뜻합니다. 레벨 50에서 한 능력치에 최대 32점, 전체에 최대 66점을 배분합니다. 모든 대표 세트는 Showdown의 M-C 세트 검증기를 통과했습니다.
- 메가 엔트리의 `name`, `types`, `base_stats`는 변신 후 형태를 표시합니다. 세트의 `species`와 `ability`는 변신 전 값을, `mega`와 `battle_ability`는 변신 후 값을 표시합니다. 메가진화 전 특성은 엔진의 기본 특성을 사용합니다.
- 한국어 명칭은 PokéAPI 데이터를 바탕으로 구성했습니다. [PokéAPI CSV](https://github.com/PokeAPI/pokeapi/tree/4e84512eaf7f58a5a50d2a27941b1191cdb9e5e9/data/v2/csv) · [PokéAPI 라이선스](https://github.com/PokeAPI/pokeapi/blob/4e84512eaf7f58a5a50d2a27941b1191cdb9e5e9/LICENSE.md)

## 카탈로그 다시 만들기

프로젝트의 시뮬레이터 설치 단계에서 Showdown 엔진 빌드를 완료한 뒤 아래 명령을 실행합니다. 원본은 `data/catalog-input/`에 받아 보관합니다.

```powershell
.\data\fetch-catalog-sources.ps1
node data/build-catalog.cjs
```
