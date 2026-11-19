# aipproject-pokemon-winrate

# 포켓몬 챔피언스 대면 승률 예측

양쪽 포켓몬과 상태를 입력하면 선택지(기술, 교체)별 승률을 보여 주는 모델 프로젝트

## 기준 시점

- 2026년 11월, 시즌 M-8 싱글, 레귤레이션 M-C
- 사용률 데이터: Smogon 2026년 9월 `gen9championsbssregmc` (1500 구간)
- 시뮬레이션 엔진: smogon/pokemon-showdown 커밋 `5b88c47` (2026-11-18)

## 담당

| 이름 | 역할 |
|---|---|
| 이도윤 | 데이터 수집, 세트 구성 |
| 강민준 | 시뮬레이션, 모델, 데모 |
| 서진서 | 분석 정리, 보고서, 발표 |

## 폴더 구조

```
data/    세트 데이터, Smogon 원본 통계(data/smogon/)
sim/     쇼다운 엔진으로 배틀을 돌리는 Node.js 코드
model/   승률 모델 학습 Python 코드
app/     Streamlit 데모
docs/    보고서, 발표 자료
```

## 처음 설치하기

### 1. 저장소 받기

```powershell
git clone https://github.com/doyun446/aipproject-pokemon-winrate.git
cd aipproject-pokemon-winrate
```

### 2. 쇼다운 엔진 설치

npm 버전은 레귤레이션 M-C가 없어서 GitHub에서 직접 받아 빌드해요.
커밋을 고정해서 팀원 모두 같은 엔진을 써요.

```powershell
cd sim
git clone https://github.com/smogon/pokemon-showdown.git engine
cd engine
git checkout 5b88c47
npm install
node build
cd ..
npm install ./engine
cd ..
```

확인 (`true`가 나오면 성공):

```powershell
node -e "const {Dex}=require('./sim/node_modules/pokemon-showdown'); console.log(Dex.formats.get('gen9championsbssregmc').exists)"
```

### 3. Python 환경

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 자주 나는 오류

- `npm.ps1을 로드할 수 없습니다`: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` 실행 후 다시 시도
- `npm warn install-scripts` 경고: 무시해도 됨

## 데이터 파일

| 파일 | 내용 |
|---|---|
| `data/sets60_draft.json` | 상위 60종, 117개 세트 (코드용) |
| `data/sets60_draft.csv` | 같은 내용 (엑셀 검토용) |
| `data/sample_sets60.*` | 종마다 대표 세트 1개 (참고용) |

### 세트를 만든 기준

- 포켓몬: 사용률 상위 60종 (메가진화는 원래 포켓몬에 합쳐서 계산)
- 세트 단위: 형태 × 도구 종류 (메가 / 구애 / 기합의띠 / 공격 강화 / 내구 / 필드·역할)
- 포함 기준: 종 안에서 비중 10% 이상인 세트는 모두 포함
- 비율(`ratio`): 포함된 세트끼리 합이 1이 되게 다시 계산
- 능력 포인트(`sp`)는 엔진의 `evs` 칸에 그대로 넣으면 됨 (변환 필요 없음)

## 범위 밖

- 강화학습
- 높은 레이팅 구간 메타 저격
