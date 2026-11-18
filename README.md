# 형세판단

Pokémon Champions 싱글에서 현재 대면의 승률과 첫 턴 선택을 비교하는 한국어 AI 데모입니다. 레벨 50, 레귤레이션 M-C, 2026년 10월 Showdown 상위 50개 포켓몬을 기준으로 합니다.

## 데모 열기

이 PC에서는 [run-demo.cmd](run-demo.cmd)를 실행하면 브라우저에서 열립니다. 다른 PC에서 처음 실행할 때는 Windows PowerShell과 Python 3.10~3.13 환경에서 저장소 폴더를 열고 아래 명령을 실행합니다.

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install --index-url https://download.pytorch.org/whl/cpu torch==2.8.0
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m streamlit run app.py
```

학습된 모델 파일이 포함되어 있어 발표 현장에서는 모델을 다시 학습하거나 Showdown 서버에 접속할 필요가 없습니다. 실행 중인 터미널에서 `Ctrl+C`를 누르면 종료됩니다.

## 발표 시연

1. **상대 HP 95% · 교체 판단**을 누릅니다. 포푸니크와 하마돈의 HP와 1:1 대면 승률을 짚고, 3:3에서는 메가한카리아스Z로 교체하라는 추천과 첫 턴 종료 예상 HP를 보여주세요.
2. **상대 HP 18% · 마무리 판단**을 누릅니다. 같은 편성에서 하마돈의 HP만 바뀌고 추천이 **속이기**로 바뀝니다. 두 가지 경우 모두 첫 선택 6개의 예상 승률을 비교할 수 있습니다.
3. **모델 검증** 탭에서 테스트에 사용한 전투 수, 기준 모델과의 비교, 확률 보정 그래프를 보여주세요.

| 하마돈 HP | 모델의 1위 선택 | 모델 승률 | 같은 선택을 400번 시뮬레이션한 승률 |
| --- | --- | ---: | ---: |
| 95% | 메가한카리아스Z 교체 | 44.7% | 52.5% |
| 18% | 속이기 | 67.3% | 97.8% |

이 시연은 조건에 따라 선택 순위가 달라지는 예시입니다. 선택 순위가 같더라도 예측 확률과 반복 시뮬레이션의 승률 사이에는 차이가 있습니다. [시연 조건](model/demo_cases.json) · [반복 시뮬레이션 결과](model/demo_validation.json)

## 화면에서 읽는 값

| 표시 | 해석 |
| --- | --- |
| 1:1 대면 예상 승률 | 화면에 나온 두 포켓몬이 교체 없이 싸울 때 아군의 승률 |
| 선택지별 경기 예상 승률 | 3:3에서 첫 턴에 해당 기술을 쓰거나 해당 포켓몬으로 교체하고, 이후 시뮬레이션 정책을 따를 때 아군의 승률 |
| 턴 종료 HP | 해당 첫 행동을 한 포켓몬의 턴 종료 시 평균 HP 비율. 교체로 들어오는 포켓몬이 맞는 공격도 반영 |
| 상대 세트 추정 | 사용률에서 구성한 대표 후보의 추정 비중. 공개된 기술·도구와 팀 내 도구 중복 제한을 반영 |

## 학습과 검증

1. **카탈로그** — 2026년 10월 Showdown M-C 사용률을 고정해 상위 50개 포켓몬·폼의 대표 세트 149개를 구성했습니다. 각 세트의 레귤레이션 적합성을 Showdown으로 검사했습니다. [출처 및 재생성](data/README.md)
2. **시뮬레이션** — 실제 Showdown Champions 엔진에서 레벨 50 전투를 반복합니다. HP·상태이상·공격/스피드 랭크·날씨와 상대 세트를 샘플링합니다. 3:3에서는 첫 턴에 가능한 기술 최대 4개와 교체 최대 2개를 각각 실행하고 경기 종료까지 진행합니다. 선택지들은 같은 난수 시드와 상대 세트로 비교합니다. 이후에는 예상 대미지와 회복·상태이상·랭크업을 고려해 기술을 선택하고 교체가 강제될 때 대기 포켓몬을 내보냅니다.
3. **지도학습** — 포켓몬·세트 임베딩과 HP, 스피드, 타입 상성, 대미지 특징을 MLP에 입력합니다. 한 출력은 시뮬레이션 승패를, 다른 출력은 첫 턴 종료 HP를 학습합니다. 1:1에서는 양쪽을 뒤집은 사례도 사용합니다. 미공개 상대 세트는 가능한 조합의 예측을 확률로 가중 평균합니다.
4. **평가** — 선봉 포켓몬의 순서 없는 쌍으로 데이터를 분할해 동일 대면의 정방향과 역방향이 학습과 평가에 걸치지 않도록 합니다. 검증 분할에서 온도 보정을 하고, 별도 평가 분할에서 Brier 점수와 로그 손실을 로지스틱 회귀 및 1:1 근사 대미지 규칙과 비교합니다. 결과와 확률 보정 그래프는 앱의 **모델 검증** 탭에서 볼 수 있습니다.

총 99,618건을 학습 70,140건, 검증 14,832건, 테스트 14,646건으로 분할했습니다. Brier 점수와 로그 손실은 낮을수록 좋습니다.

| 평가 범위 | 표본 | MLP Brier | 로지스틱 Brier | MLP 로그 손실 |
| --- | ---: | ---: | ---: | ---: |
| 전체 | 14,646 | 0.1865 | 0.2025 | 0.5491 |
| 1:1 | 6,078 | 0.1472 | 0.1781 | 0.4534 |
| 3:3 | 8,568 | 0.2144 | 0.2199 | 0.6170 |

1:1 근사 대미지 규칙의 Brier 점수는 0.1865였습니다. 학습 대면을 25%, 50%, 100% 사용했을 때 전체 Brier 점수는 각각 0.2036, 0.1926, 0.1865였습니다. 대표 세트의 능력 포인트를 이동한 별도 3,644건에서도 평가했습니다. [실험 기록](model/metrics.json)

학습에 쓰지 않은 1:1 대면 100개를 각각 300번 다시 시뮬레이션했습니다. 각 대면의 반복 시뮬레이션 승률과 모델 예측은 평균 21.2%p 차이가 났습니다. 대면별 승률은 대략적인 추정치로 해석해야 합니다. [반복 검증 결과](model/holdout.json)

### 모델 다시 학습하기

Node.js 22 이상과 Git이 필요합니다. 엔진 설치에만 네트워크가 필요합니다. 첫 줄은 npm 패키지 버전을 고정하고, 두 번째 줄은 고정된 Showdown 버전을 받아 빌드합니다.

```powershell
npm.cmd ci
node sim/setup-engine.mjs
node sim/generate.mjs --duels 4500 --teams 1100 --trials 3 --seed 20261119 --output data/generated/main-1.jsonl
node sim/generate.mjs --duels 4500 --teams 1100 --trials 3 --seed 20261120 --output data/generated/main-2.jsonl
node sim/generate.mjs --duels 4500 --teams 1100 --trials 3 --seed 20261121 --output data/generated/main-3.jsonl
node sim/generate.mjs --alternate-sp --duels 750 --teams 180 --trials 2 --seed 20261201 --output data/generated/alternate-sp.jsonl
.venv\Scripts\python.exe -m winrate.train --data data/generated/main-1.jsonl data/generated/main-2.jsonl data/generated/main-3.jsonl --epochs 40 --threads 4 --batch-size 512 --alternate-sp-data data/generated/alternate-sp.jsonl --learning-curve
.venv\Scripts\python.exe -m winrate.validate
```

## 적용 범위

- 수치는 입력한 전투 상태와 시뮬레이터의 행동 정책에 따라 달라집니다. 실제 유저 경기에서의 승률로 해석할 수 있는지는 별도 검증이 필요합니다.
- 주요 HP·상태·날씨와 공격/스피드 랭크를 입력할 수 있습니다. 현재 보이는 메가 진화 폼은 변신한 상태로, 교체 후보의 메가 폼은 기본 폼으로 교체한 뒤 공격할 때 진화하는 것으로 가정합니다.
- 상대 세트 비중은 개별 사용률 통계로부터 추정한 값입니다. 래더에서 해당 기술·도구·특성이 함께 쓰인 정확한 확률은 집계 자료에서 제공하지 않습니다.

[레귤레이션 M-C 공지](https://news.pokemon-home.com/ko/page/816.html) · [Pokémon Showdown](https://github.com/smogon/pokemon-showdown) · [2026년 10월 Showdown 통계](https://www.smogon.com/stats/2026-10/gen9championsbssregmc-1760.txt)
