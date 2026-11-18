# 형세판단

Pokémon Champions 싱글에서 현재 대면의 승률과 첫 턴 선택을 비교하는 한국어 AI 데모입니다. 레벨 50, 레귤레이션 M-C, 2026년 10월 Showdown 사용률을 기준으로 합니다. 메가와 지역폼을 같은 종으로 묶어 **60종**을 선정하고, 전투에서는 95개 폼과 대표 세트 279개를 구분합니다. [카탈로그 선정 기준](data/README.md)

## 데모 열기

이 PC에서는 [run-demo.cmd](run-demo.cmd)를 실행하면 브라우저에서 열립니다. 다른 Windows PC에서는 Python 3.10~3.13을 설치하고 저장소 폴더에서 다음 명령을 실행합니다.

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install --index-url https://download.pytorch.org/whl/cpu torch==2.8.0
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m streamlit run app.py
```

학습된 모델 파일이 포함되어 있어 데모는 Showdown에 접속하지 않고 실행할 수 있어요. 실행 중인 터미널에서 `Ctrl+C`를 누르면 종료됩니다.

## 상대 선택과 예측 해석

- **상대 탭**에서 선봉과 대기를 고릅니다. 메가·지역폼이 여러 개면 형태 선택기가 나타납니다. 선봉과 대기 각각의 세트 메뉴에서 대표 세트를 직접 고르거나 **사용률로 추정**을 선택할 수 있습니다.
- 추정할 때 선봉의 공개된 기술·도구를 입력하면 일치하는 세트들로 좁힙니다. 3:3에서는 팀 내 도구 중복 제한을 적용합니다.
- **1:1 대면 예상 승률**은 화면에 나온 두 포켓몬이 교체 없이 싸우는 조건의 아군 승률입니다. **3:3 선택지별 승률**은 첫 행동을 선택한 뒤 시뮬레이션 정책을 따라 경기 끝까지 갔을 때의 아군 승률입니다.
- 상위 두 선택지의 차이가 3%p 이하이면 **선택 차이 작음**, 가능한 상대 세트에 따라 상위 행동의 승률 범위가 10%p 이상이면 **상대 세트에 민감**을 표시합니다. 선택지의 간격과 세트에 따른 변화 폭을 보여주는 기준입니다.

## 발표 시연

준비한 대면은 **포푸니크 vs 하마돈**입니다.

1. **상대 HP 95%**에서 양쪽 HP와 대면 승률을 보여주고, 3:3의 첫 선택 6개를 비교합니다.
2. **상대 HP 18%**로 바꾸고 상위 선택의 차이를 봅니다. 차이가 작으면 화면에서 접전을 알려줘요.
3. 상대 탭에서 하마돈의 도구가 다른 대표 세트를 직접 골라, 상대 정보가 선택지별 승률에 어떻게 반영되는지 보여줍니다.

| 조건 | 모델에서 가장 높은 선택 | 모델 승률 | 이 선택을 400판 반복한 승률 |
| --- | --- | ---: | ---: |
| 상대 HP 95% | 메가한카리아스Z 교체 | 41.0% | 52.5% |
| 상대 HP 18% | 속이기 | 69.2% | 97.8% |

발표에서는 첫 턴 행동 간 순위와 추정 오차를 설명합니다.

[발표용 PowerPoint](docs/battle-winrate-demo.pptx) · [시연 조건](model/demo_cases.json) · [시연 반복 결과](model/demo_validation.json)

## 학습과 검증

Showdown Champions에서 HP·공격/스피드 랭크·상태이상·날씨를 바꿔 **89,850건**을 생성했습니다. 1:1은 45,000건, 3:3은 44,850건입니다. 3:3에서는 기술과 교체를 첫 행동으로 하나씩 적용하고, 예상 대미지·회복·상태이상·랭크업을 고려하는 정책으로 경기 끝까지 진행했습니다. 승부와 첫 턴 종료 HP를 기록했습니다.

레벨 50 능력치·타입·HP 대비 근사 대미지·쓰러뜨리는 데 필요한 추정 타격 수에 포켓몬과 세트 임베딩을 결합해 PyTorch MLP를 학습했습니다. 1:1에는 좌우 뒤집기를 적용했고, 모드별 온도 보정을 적용했습니다. 기본 종의 순서 없는 쌍을 기준으로 학습 **64,179건**, 보정 **12,969건**, 테스트 **12,702건**을 나눴습니다.

| 테스트 범위 | 표본 | MLP Brier | 로지스틱 Brier | MLP 로그 손실 |
| --- | ---: | ---: | ---: | ---: |
| 전체 | 12,702 | 0.1727 | 0.1792 | 0.5136 |
| 1:1 | 6,552 | 0.1401 | 0.1544 | 0.4315 |
| 3:3 | 6,150 | 0.2074 | 0.2056 | 0.6011 |

Brier 점수와 로그 손실은 낮을수록 좋습니다. 1:1 근사 대미지 규칙의 Brier 점수는 0.1762였습니다. 대표 세트와 겹치는 배분을 제외한 별도 능력 포인트 평가에는 3,213건을 사용했습니다.

학습에 쓰지 않은 1:1 대면 100개를 각각 300판씩 돌렸을 때, 대면별 예측과 반복 시뮬레이션 승률은 평균 **19.3%p** 차이가 났습니다. 시뮬레이션 승률이 40~60%인 대면 6개에서는 평균 15.5%p 차이가 났습니다. 승률은 해당 시뮬레이션 정책과 세트 가정에 따른 추정치입니다. [학습 지표](model/metrics.json) · [반복 검증](model/holdout.json)

### 재현 방법

Node.js 22 이상과 Git이 필요합니다. 엔진 설치에는 네트워크가 필요합니다.

```powershell
npm.cmd ci
node sim/setup-engine.mjs
npm.cmd test
for ($i = 1; $i -le 5; $i++) {
    $seed = 20261118 + $i
    node sim/generate.mjs --duels 3000 --teams 500 --trials 3 --seed $seed --output "data/generated/main-$i.jsonl"
}
node sim/generate.mjs --alternate-sp --duels 750 --teams 180 --trials 2 --seed 20261201 --output data/generated/alternate-sp.jsonl
.venv\Scripts\python.exe -m winrate.train --data data/generated/main-1.jsonl data/generated/main-2.jsonl data/generated/main-3.jsonl data/generated/main-4.jsonl data/generated/main-5.jsonl --epochs 40 --threads 4 --batch-size 512 --alternate-sp-data data/generated/alternate-sp.jsonl --learning-curve
.venv\Scripts\python.exe -m winrate.validate
```

[레귤레이션 M-C 공지](https://news.pokemon-home.com/ko/page/816.html) · [Pokémon Showdown](https://github.com/smogon/pokemon-showdown) · [2026년 10월 사용률](https://www.smogon.com/stats/2026-10/gen9championsbssregmc-1760.txt)
