import html
import json
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from winrate import Predictor


ROOT = Path(__file__).resolve().parent
CATALOG = ROOT / "data" / "catalog.json"
CHECKPOINT = ROOT / "model" / "model.pt"
METRICS = ROOT / "model" / "metrics.json"
HOLDOUT = ROOT / "model" / "holdout.json"
DEMO_CASES = ROOT / "model" / "demo_cases.json"

WEATHER = {"": "없음", "rain": "비", "sun": "쾌청", "sand": "모래바람", "snow": "눈"}
STATUS = {
    "": "정상", "brn": "화상", "par": "마비", "psn": "독", "tox": "맹독",
    "slp": "잠듦", "frz": "얼음",
}
TYPES = {
    "Normal": ("노말", "#aab2bf"), "Fire": ("불꽃", "#ff8a61"),
    "Water": ("물", "#79aeff"), "Electric": ("전기", "#ffe278"),
    "Grass": ("풀", "#9de581"), "Ice": ("얼음", "#a3e9ff"),
    "Fighting": ("격투", "#ff9778"), "Poison": ("독", "#d998fa"),
    "Ground": ("땅", "#e2b27a"), "Flying": ("비행", "#b1baff"),
    "Psychic": ("에스퍼", "#ff9cc0"), "Bug": ("벌레", "#c6dc63"),
    "Rock": ("바위", "#dac18e"), "Ghost": ("고스트", "#c6a5f1"),
    "Dragon": ("드래곤", "#ad9dff"), "Dark": ("악", "#c5aab7"),
    "Steel": ("강철", "#afe0e5"), "Fairy": ("페어리", "#ffc3de"),
}
TYPE_IMMUNITIES = {
    "Fire": {"brn"}, "Electric": {"par"}, "Poison": {"psn", "tox"},
    "Steel": {"psn", "tox"}, "Ice": {"frz"},
}


@st.cache_data
def read_json(path, modified_at):
    return Path(path).read_text(encoding="utf-8-sig")


def load_json(path):
    return json.loads(read_json(str(path), path.stat().st_mtime_ns))


@st.cache_resource
def load_predictor(model_path, catalog_path, model_modified_at, catalog_modified_at):
    return Predictor.load(model_path, catalog_path)


def esc(value):
    return html.escape(str(value))


def to_id(value):
    return "".join(char for char in value.lower() if char.isascii() and char.isalnum())


def localized(catalog, value, kind):
    if not value:
        return "없음"
    return catalog.get(f"{kind}_names_ko", {}).get(to_id(value), value)


def pokemon_name(entry):
    return entry.get("name_ko") or entry["name"]


def set_name(set_data):
    return set_data.get("name_ko") or set_data.get("name") or set_data["id"]


def index_for(options, value):
    return options.index(value) if value in options else 0


def active_controls(side, entries, start, weather):
    ids = list(entries)
    selected = st.selectbox(
        f"{side} 포켓몬", ids, index=index_for(ids, start.get("pokemon")),
        format_func=lambda value: pokemon_name(entries[value]), key=f"{side}-active",
    )
    pokemon = entries[selected]
    result = {
        "pokemon": selected, "set": None, "attack": 0, "speed": 0,
    }
    abilities = {
        row.get("battle_ability") or row["ability"] for row in pokemon["sets"]
    }
    if side == "아군":
        sets = {row["id"]: row for row in pokemon["sets"]}
        result["set"] = st.selectbox(
            "아군 세트", list(sets), index=index_for(list(sets), start.get("set")),
            format_func=lambda value: set_name(sets[value]), key=f"own-set-{selected}",
        )
        known = sets[result["set"]]
        abilities = {known.get("battle_ability") or known["ability"]}
    result["hp"] = st.slider(
        f"{side} HP", 1, 100, int(start.get("hp", 100)), key=f"{side}-hp",
    )
    blocked = set().union(*(TYPE_IMMUNITIES.get(kind, set()) for kind in pokemon["types"]))
    if weather == "sun":
        blocked.add("frz")
    if abilities == {"Thermal Exchange"}:
        blocked.add("brn")
    statuses = [condition for condition in STATUS if condition not in blocked]
    result["status"] = st.selectbox(
        f"{side} 상태이상", statuses, index=index_for(statuses, start.get("status", "")),
        format_func=STATUS.__getitem__, key=f"{side}-status",
    )
    with st.expander(f"{side} 랭크 조정"):
        result["attack"] = st.slider(
            "공격 랭크", -6, 6, int(start.get("attack", 0)), key=f"{side}-attack",
        )
        result["speed"] = st.slider(
            "스피드 랭크", -6, 6, int(start.get("speed", 0)), key=f"{side}-speed",
        )
    return result


def base_species(entry):
    return entry.get("base_species", entry["id"])


def bench_controls(side, active, entries, start):
    active_entry = entries[active["pokemon"]]
    team = [active]
    used_species = {base_species(active_entry)}
    used_mega = active_entry["mega"]
    used_items = set()
    if active["set"]:
        active_set = next(row for row in active_entry["sets"] if row["id"] == active["set"])
        if active_set["item"]:
            used_items.add(active_set["item"])
    for slot in (1, 2):
        options = [
            key for key, entry in entries.items()
            if base_species(entry) not in used_species
            and not (used_mega and entry["mega"])
            and any(row["item"] not in used_items for row in entry["sets"])
        ]
        slot_start = start[slot] if len(start) > slot else {}
        key = st.selectbox(
            f"{side} 대기 {slot}", options, index=index_for(options, slot_start.get("pokemon")),
            format_func=lambda value: pokemon_name(entries[value]), key=f"{side}-bench-{slot}",
        )
        pokemon = entries[key]
        used_species.add(base_species(pokemon))
        used_mega = used_mega or pokemon["mega"]
        selected_set = None
        if side == "아군":
            sets = {row["id"]: row for row in pokemon["sets"] if row["item"] not in used_items}
            selected_set = st.selectbox(
                f"대기 {slot} 세트", list(sets), index=index_for(list(sets), slot_start.get("set")),
                format_func=lambda value: set_name(sets[value]), key=f"own-bench-{slot}-set-{key}",
            )
            if sets[selected_set]["item"]:
                used_items.add(sets[selected_set]["item"])
        hp = st.slider(
            f"{side} 대기 {slot} HP", 1, 100, int(slot_start.get("hp", 100)),
            key=f"{side}-bench-{slot}-hp",
        )
        team.append({
            "pokemon": key, "set": selected_set, "hp": hp,
            "status": "", "attack": 0, "speed": 0,
        })
    return team


def type_badges(types):
    return "".join(
        f'<span class="type-chip" style="--type:{color}">{esc(label)}</span>'
        for name in types
        for label, color in [TYPES.get(name.title(), (name, "#aab2bf"))]
    )


def fighter_card(state, entry, side, label):
    hp = int(state["hp"])
    notes = [STATUS[state["status"]]]
    for key, text in (("attack", "공격"), ("speed", "스피드")):
        if state[key]:
            notes.append(f"{text} {state[key]:+d}")
    types = type_badges(entry["types"])
    return (
        f'<div class="fighter {side}"><div class="fighter-role">{label}</div>'
        f'<div class="fighter-name">{esc(pokemon_name(entry))}</div>'
        f'<div class="fighter-types">{types}</div>'
        f'<div class="hp-label"><span>HP</span><strong>{hp}%</strong></div>'
        f'<div class="track hp-track" role="meter" aria-label="{label} HP" '
        f'aria-valuemin="0" aria-valuemax="100" aria-valuenow="{hp}">'
        f'<span style="width:{hp}%"></span></div>'
        f'<div class="fighter-note">{esc(" · ".join(notes))}</div></div>'
    )


def matchup(scenario, entries, probability):
    own = scenario["own"][0]
    foe = scenario["foe"][0]
    left = fighter_card(own, entries[own["pokemon"]], "own", "아군")
    right = fighter_card(foe, entries[foe["pokemon"]], "foe", "상대")
    chance = 100 * probability
    tone = "up" if chance >= 55 else "down" if chance <= 45 else "even"
    verdict = {"up": "아군 우세", "down": "상대 우세", "even": "접전"}[tone]
    st.html(
        f'<div class="matchup">{left}<div class="forecast"><div class="forecast-label">1:1 대면 예상 승률</div>'
        f'<div class="forecast-value {tone}">{chance:.1f}<span>%</span></div>'
        f'<div class="forecast-verdict {tone}">{verdict}</div>'
        f'<div class="balance" role="meter" aria-label="아군 대면 예상 승률" '
        f'aria-valuemin="0" aria-valuemax="100" aria-valuenow="{chance:.1f}">'
        f'<span style="width:{chance:.1f}%"></span><i></i></div>'
        f'<div class="forecast-foot">날씨 · {esc(WEATHER[scenario["weather"]])}</div></div>{right}</div>'
    )


def ordered_actions(scenario, entries, catalog, legal_actions):
    own = scenario["own"][0]
    pokemon = entries[own["pokemon"]]
    known_set = next(row for row in pokemon["sets"] if row["id"] == own["set"])
    actions = {f"move:{idx}": localized(catalog, move, "move") for idx, move in enumerate(known_set["moves"])}
    for idx, member in enumerate(scenario["own"][1:], 1):
        actions[f"switch:{idx}"] = pokemon_name(entries[member["pokemon"]])
    return {action: actions[action] for action in legal_actions}


def decision_chart(results, names):
    sorted_results = sorted(results, key=lambda row: row["win"], reverse=True)
    best, runner_up = sorted_results[:2]
    lead = 100 * (best["win"] - runner_up["win"])
    best_action = best["action"]
    best_name = names[best_action]
    decision = "교체" if best_action.startswith("switch:") else "기술"
    st.html(
        f'<div class="recommendation"><div><span class="recommend-label">추천 {decision}</span>'
        f'<strong>{esc(best_name)}</strong></div>'
        f'<div class="recommend-score">{100 * best["win"]:.1f}%'
        f'<small> · 다음 선택지보다 {lead:.1f}%p</small></div></div>'
    )
    rows = []
    for result in sorted_results:
        action = result["action"]
        mode = "교체" if action.startswith("switch:") else "기술"
        win, hp = 100 * result["win"], result["hp_after"]
        best_class = "best" if action == best_action else ""
        rows.append(
            f'<div class="choice {best_class}"><div class="choice-name">'
            f'<span class="choice-kind">{mode}</span><strong>{esc(names[action])}</strong></div>'
            f'<div class="chance-cell"><div class="track choice-track" aria-hidden="true">'
            f'<span style="width:{win:.2f}%"></span></div><strong>{win:.1f}%</strong></div>'
            f'<div class="choice-hp">{hp:.0f}%</div></div>'
        )
    st.html(
        '<div class="choices"><div class="choice choice-header"><span>첫 턴 선택</span>'
        '<span>경기 예상 승률</span><span>턴 종료 HP</span></div>'
        + "".join(rows) + "</div>"
    )
    st.caption("첫 턴에 각 행동을 선택한 뒤 시뮬레이션 정책을 따랐을 때의 경기 승률이에요. HP는 그 행동으로 나온 포켓몬의 첫 턴 종료 예상치예요.")


def opponent_panels(rows, catalog):
    st.subheader("상대 세트 추정")
    if not rows:
        st.info("공개된 정보에 맞는 세트가 등록되어 있지 않아요.")
        return
    cards = []
    for row in sorted(rows, key=lambda item: item["probability"], reverse=True):
        probability = 100 * row["probability"]
        item = localized(catalog, row.get("item"), "item")
        ability = localized(catalog, row.get("battle_ability") or row.get("ability"), "ability")
        moves = "".join(
            f'<span class="move-chip">{esc(localized(catalog, move, "move"))}</span>'
            for move in row["moves"]
        )
        cards.append(
            f'<div class="set-card"><div class="set-title"><strong>{esc(set_name(row))}</strong>'
            f'<span>{probability:.0f}%</span></div><div class="set-detail">{esc(item)} · {esc(ability)}</div>'
            f'<div class="set-moves">{moves}</div></div>'
        )
    st.html('<div class="sets">' + "".join(cards) + "</div>")
    st.caption("사용률 통계에서 구성한 후보 세트의 추정 비중이에요. 기술과 도구를 공개하면 일치하는 후보끼리 비중을 다시 계산해요.")


def evaluation():
    st.subheader("학습과 검증")
    if not METRICS.is_file():
        st.info("학습 지표 파일을 생성하면 이곳에서 확인할 수 있어요.")
        return
    metrics = load_json(METRICS)
    data = metrics["data"]
    st.caption(
        f'시뮬레이션 {data["trials"]:,}건 · '
        f'학습 {data["split"]["train"]:,}건 · 확률 보정 {data["split"]["validation"]:,}건 · '
        f'최종 평가 {data["split"]["test"]:,}건'
    )
    labels = {"overall": "전체", "duel": "1:1 대면", "team": "3:3 선택"}
    category = st.radio("평가 범위", labels, format_func=labels.__getitem__, horizontal=True)
    evaluation_rows = metrics[category]
    names = {"mlp": "임베딩 + MLP", "logistic": "로지스틱 회귀", "damage_rule": "대미지 규칙"}
    table = []
    curve = []
    for key, name in names.items():
        if key not in evaluation_rows:
            continue
        item = evaluation_rows[key]
        table.append({
            "모델": name, "Brier 점수": round(item["brier"], 4),
            "로그 손실": round(item["log_loss"], 4), "평가 표본": item["n"],
        })
        for point in item.get("calibration", []):
            if point["count"]:
                curve.append({
                    "모델": name, "예측 승률": point["predicted"],
                    "실제 승률": point["observed"], "표본 수": point["count"],
                })
    st.dataframe(pd.DataFrame(table), hide_index=True, width="stretch")
    st.caption("Brier 점수와 로그 손실은 낮을수록 좋아요. 평가 표본은 시뮬레이션 결과를 기준으로 해요.")
    if curve:
        points = alt.Chart(pd.DataFrame(curve)).mark_line(point=True).encode(
            x=alt.X("예측 승률:Q", axis=alt.Axis(format="%"), scale=alt.Scale(domain=[0, 1])),
            y=alt.Y("실제 승률:Q", axis=alt.Axis(format="%"), scale=alt.Scale(domain=[0, 1])),
            color=alt.Color("모델:N"),
            tooltip=["모델:N", alt.Tooltip("예측 승률:Q", format=".1%"), alt.Tooltip("실제 승률:Q", format=".1%"), "표본 수:Q"],
        )
        reference = alt.Chart(pd.DataFrame({"예측 승률": [0, 1], "실제 승률": [0, 1]})).mark_line(
            strokeDash=[5, 5], color="#748395",
        ).encode(x="예측 승률:Q", y="실제 승률:Q")
        st.altair_chart((reference + points).properties(height=310), use_container_width=True)
        st.caption("확률 보정 그래프에서 점선에 가까울수록, 같은 확률로 예측된 표본들의 실제 승률이 예측값과 비슷해요.")
    if "learning_curve" in metrics:
        sample_counts = [
            {"학습 대면 수": row["train_matchups"], "Brier 점수": row[category]["brier"]}
            for row in metrics["learning_curve"]
            if category in row and "brier" in row[category]
        ]
        if sample_counts:
            with st.expander("학습 데이터 규모별 결과"):
                st.line_chart(pd.DataFrame(sample_counts), x="학습 대면 수", y="Brier 점수")
    if "alternate_sp" in metrics and category in metrics["alternate_sp"]:
        extra = metrics["alternate_sp"][category]
        if "brier" in extra:
            st.caption(f'미학습 능력 포인트 배분 · 평가 {extra["n"]:,}건 · Brier {extra["brier"]:.4f}')
    if HOLDOUT.is_file() and category != "team":
        summary = load_json(HOLDOUT)
        with st.expander("1:1 대면 승률 반복 검증"):
            st.write(
                f'학습에 쓰지 않은 {summary["cases"]}개 대면을 '
                f'각각 {summary["trials_per_case"]}번 시뮬레이션했어요. '
                f'모델의 대면별 예측과 시뮬레이션 승률은 평균 {100 * summary["probability_mae"]:.1f}%p 차이가 났어요.'
            )


def change_preset(case):
    for key in list(st.session_state):
        if key.startswith(("아군-", "상대-", "own-set-", "own-bench-", "revealed-", "weather", "mode")):
            del st.session_state[key]
    st.session_state["start"] = case


def main():
    st.set_page_config(page_title="형세판단 · Champions", page_icon="◈", layout="wide")
    st.html(ROOT / "assets" / "dashboard.css")
    st.html(
        '<header class="dash-header"><div class="dash-project">POKÉMON CHAMPIONS ANALYTICS</div>'
        '<h1>형세판단<span>.</span></h1><p>지금 이 대면에서 어떤 선택이 유리할까?</p>'
        '<div class="dash-line"></div></header>'
    )
    if not CATALOG.is_file() or not CHECKPOINT.is_file():
        st.error("카탈로그 또는 학습 모델이 없어요. README의 학습 방법으로 두 파일을 준비해 주세요.")
        return
    catalog = load_json(CATALOG)
    entries = {row["id"]: row for row in catalog["pokemon"]}
    predictor = load_predictor(str(CHECKPOINT), str(CATALOG), CHECKPOINT.stat().st_mtime_ns, CATALOG.stat().st_mtime_ns)
    cases = load_json(DEMO_CASES) if DEMO_CASES.is_file() else []
    if "start" not in st.session_state:
        st.session_state["start"] = cases[0]["scenario"] if cases else {}
    start = st.session_state["start"]
    sim_tab, eval_tab = st.tabs(["대면 분석", "모델 검증"])
    with sim_tab:
        inputs, results = st.columns([1, 2.4], gap="large")
        with inputs:
            st.subheader("전투 설정")
            if cases:
                with st.expander("발표 시연", expanded=True):
                    for case in cases:
                        st.button(
                            case["label"], key=f'demo-{case["id"]}', width="stretch",
                            on_click=change_preset, args=(case["scenario"],),
                        )
            modes = ["team", "duel"]
            mode = st.radio(
                "배틀 모드", modes, index=index_for(modes, start.get("mode")),
                format_func={"duel": "1:1 대면", "team": "3:3 선택 비교"}.__getitem__,
                horizontal=True, key="mode",
            )
            weather = st.selectbox(
                "날씨", list(WEATHER), index=index_for(list(WEATHER), start.get("weather", "")),
                format_func=WEATHER.__getitem__, key="weather",
            )
            own_start = start.get("own", [{"pokemon": "garchomp"}])
            foe_start = start.get("foe", [{"pokemon": "rotomwash"}])
            left, right = st.tabs(["아군", "상대"])
            with left:
                own_active = active_controls("아군", entries, own_start[0], weather)
                own = [own_active]
                if mode == "team":
                    with st.expander("아군 교체 후보"):
                        own = bench_controls("아군", own_active, entries, own_start)
            with right:
                foe_active = active_controls("상대", entries, foe_start[0], weather)
                foe = [foe_active]
                if mode == "team":
                    with st.expander("상대 대기 포켓몬"):
                        foe = bench_controls("상대", foe_active, entries, foe_start)
                with st.expander("공개된 상대 정보"):
                    active_sets = entries[foe_active["pokemon"]]["sets"]
                    possible_moves = sorted({move for row in active_sets for move in row["moves"]})
                    possible_items = sorted({row["item"] for row in active_sets if row.get("item")})
                    revealed_move = st.selectbox(
                        "확인한 기술", [None, *possible_moves],
                        format_func=lambda value: localized(catalog, value, "move") if value else "미확인",
                        key=f'revealed-move-{foe_active["pokemon"]}',
                    )
                    revealed_item = st.selectbox(
                        "확인한 도구", [None, *possible_items],
                        format_func=lambda value: localized(catalog, value, "item") if value else "미확인",
                        key=f'revealed-item-{foe_active["pokemon"]}',
                    )
                    if revealed_move:
                        foe_active["revealed_moves"] = [revealed_move]
                    if revealed_item:
                        foe_active["revealed_item"] = revealed_item
        with results:
            scenario = {"mode": mode, "own": own, "foe": foe, "weather": weather}
            duel = {"mode": "duel", "own": [own_active], "foe": [foe_active], "weather": weather}
            try:
                inferred = predictor.opponent_sets(scenario)
            except ValueError:
                st.warning("공개된 정보와 도구 중복 제한을 함께 만족하는 상대 세트가 없어요. 상대 포켓몬이나 공개 정보를 조정해 주세요.")
            else:
                duel_result = predictor.predict(duel, ["auto"])[0]
                matchup(scenario, entries, duel_result["win"])
                if mode == "team":
                    st.subheader("선택지별 승률")
                    legal_actions = predictor.legal_actions(scenario)
                    names = ordered_actions(scenario, entries, catalog, legal_actions)
                    if "switch:1" not in names:
                        st.caption("상대의 특성으로 이번 턴에는 아군을 교체할 수 없어요.")
                    decision_chart(predictor.predict(scenario, list(names)), names)
                else:
                    st.caption(f'첫 턴 종료 시 아군 예상 HP는 {duel_result["hp_after"]:.0f}%예요.')
                opponent_panels(inferred, catalog)
            source = catalog["source"]
            st.caption(
                f'레벨 50 · [레귤레이션 M-C]({source["rules_url"]}) · '
                f'[Showdown 사용률 {source["month"]}]({source["usage_url"]})'
            )
    with eval_tab:
        evaluation()


if __name__ == "__main__":
    main()
