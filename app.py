import html
import json
from itertools import product
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
ABILITY_IMMUNITIES = {
    "Comatose": set(STATUS) - {""}, "Purifying Salt": set(STATUS) - {""},
    "Immunity": {"psn", "tox"}, "Pastel Veil": {"psn", "tox"},
    "Insomnia": {"slp"}, "Sweet Veil": {"slp"}, "Vital Spirit": {"slp"},
    "Limber": {"par"}, "Magma Armor": {"frz"},
    "Thermal Exchange": {"brn"}, "Water Bubble": {"brn"}, "Water Veil": {"brn"},
}
CLOSE_CHOICE_MARGIN = 3.0
SET_SENSITIVITY_MARGIN = 10.0


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


def select_option(label, options, default, format_option, key, **kwargs):
    if key in st.session_state and st.session_state[key] not in options:
        del st.session_state[key]
    return st.selectbox(
        label, options, index=index_for(options, default), format_func=format_option,
        key=key, **kwargs,
    )


def base_species(entry):
    return entry.get("base_species", entry["id"])


def select_pokemon(label, entries, options, initial, key):
    groups = {}
    for pokemon_id in options:
        row = entries[pokemon_id]
        species = base_species(row)
        groups.setdefault(species, []).append(pokemon_id)
    initial = initial if initial in entries else options[0]

    def species_label(species):
        first = entries[groups[species][0]]
        return first.get("base_name_ko") or pokemon_name(entries.get(species, first))

    species = select_option(
        label, list(groups), base_species(entries[initial]), species_label, key,
    )
    forms = groups[species]
    if len(forms) == 1:
        return forms[0]
    default_form = max(forms, key=lambda pokemon_id: entries[pokemon_id].get("usage", 0))
    return select_option(
        f"{label} 형태", forms, initial if initial in forms else default_form,
        lambda value: pokemon_name(entries[value]), f"{key}-form-{species}",
    )


def select_set(label, candidates, initial, catalog, key, hidden=False):
    sets = {row["id"]: row for row in candidates}
    options = [None, *sets] if hidden else list(sets)

    def option_label(set_id):
        if set_id is None:
            return "사용률로 추정"
        row = sets[set_id]
        item = localized(catalog, row.get("item"), "item")
        move = localized(catalog, row["moves"][0], "move")
        return f"{set_name(row)} · {item} · {move}"

    return select_option(
        label, options, initial, option_label, key,
        help="상대의 도구·특성·기술을 알고 있다면 해당 세트를 직접 골라요." if hidden else None,
    )


def active_controls(side, entries, catalog, start, weather):
    is_foe = side == "상대"
    selected = select_pokemon(
        f"{side} 포켓몬", entries, list(entries), start.get("pokemon"), f"{side}-active",
    )
    pokemon = entries[selected]
    selected_set = select_set(
        f"{side} 세트", pokemon["sets"], start.get("set"), catalog,
        f"{side}-set-{selected}", hidden=is_foe,
    )
    result = {
        "pokemon": selected, "set": selected_set, "attack": 0, "speed": 0,
    }
    candidates = [row for row in pokemon["sets"] if selected_set is None or row["id"] == selected_set]
    blocked = set().union(*(TYPE_IMMUNITIES.get(kind, set()) for kind in pokemon["types"]))
    blocked.update(set.intersection(*[
        ABILITY_IMMUNITIES.get(row.get("battle_ability") or row["ability"], set())
        for row in candidates
    ]))
    if weather == "sun":
        blocked.add("frz")
    statuses = [condition for condition in STATUS if condition not in blocked]
    result["hp"] = st.slider(
        f"{side} HP", 1, 100, int(start.get("hp", 100)), key=f"{side}-hp",
    )
    result["status"] = select_option(
        f"{side} 상태이상", statuses, start.get("status", ""), STATUS.__getitem__, f"{side}-status",
    )
    with st.expander(f"{side} 랭크 조정"):
        result["attack"] = st.slider(
            "공격 랭크", -6, 6, int(start.get("attack", 0)), key=f"{side}-attack",
        )
        result["speed"] = st.slider(
            "스피드 랭크", -6, 6, int(start.get("speed", 0)), key=f"{side}-speed",
        )
    if is_foe and selected_set is None:
        reveal_foe_info(result, pokemon, catalog)
    return result


def reveal_foe_info(slot, pokemon, catalog):
    known_pokemon = slot["pokemon"]
    with st.expander("공개된 상대 정보"):
        candidates = pokemon["sets"]
        possible_moves = sorted({move for row in candidates for move in row["moves"]})
        revealed_move = select_option(
            "확인한 기술", [None, *possible_moves], None,
            lambda value: localized(catalog, value, "move") if value else "미확인",
            f"revealed-move-{known_pokemon}",
        )
        if revealed_move:
            slot["revealed_moves"] = [revealed_move]
            candidates = [row for row in candidates if revealed_move in row["moves"]]
        possible_items = sorted({row["item"] for row in candidates if row.get("item")})
        revealed_item = select_option(
            "확인한 도구", [None, *possible_items], None,
            lambda value: localized(catalog, value, "item") if value else "미확인",
            f"revealed-item-{known_pokemon}",
        )
        if revealed_item:
            slot["revealed_item"] = revealed_item


def item_options(sets):
    return {to_id(row["item"]) if row.get("item") else "" for row in sets}


def can_add_item(previous, item):
    for combination in product(*previous, (item,)):
        held = [value for value in combination if value]
        if len(held) == len(set(held)):
            return True
    return False


def bench_controls(side, active, entries, catalog, start, compatible_sets):
    is_foe = side == "상대"
    active_entry = entries[active["pokemon"]]
    team = [active]
    used_species = {base_species(active_entry)}
    used_mega = active_entry["mega"]
    previous_items = [item_options(row for row, _ in compatible_sets(active))]
    for slot in (1, 2):
        available_sets = {}
        for key, entry in entries.items():
            if base_species(entry) in used_species or (used_mega and entry["mega"]):
                continue
            candidates = [
                row for row in entry["sets"]
                if can_add_item(previous_items, to_id(row.get("item") or ""))
            ]
            if candidates:
                available_sets[key] = candidates
        slot_start = start[slot] if len(start) > slot else {}
        key = select_pokemon(
            f"{side} 대기 {slot}", entries, list(available_sets), slot_start.get("pokemon"),
            f"{side}-bench-{slot}",
        )
        pokemon = entries[key]
        used_species.add(base_species(pokemon))
        used_mega = used_mega or pokemon["mega"]
        selected_set = select_set(
            f"{side} 대기 {slot} 세트", available_sets[key], slot_start.get("set"),
            catalog, f"{side}-bench-{slot}-set-{key}", hidden=is_foe,
        )
        possible_sets = [
            row for row in available_sets[key] if selected_set is None or row["id"] == selected_set
        ]
        previous_items.append(item_options(possible_sets))
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
    close = lead <= CLOSE_CHOICE_MARGIN
    banner_class = "recommendation is-close" if close else "recommendation"
    st.html(
        f'<div class="{banner_class}"><div><span class="recommend-label">추천 {decision}</span>'
        f'<strong>{esc(best_name)}</strong></div>'
        f'<div class="recommend-score">{100 * best["win"]:.1f}%'
        f'<small> · 다음 선택지보다 {lead:.1f}%p</small></div></div>'
    )
    notes = []
    if close:
        notes.append((
            "선택 차이 작음",
            f"예상 승률 상위 두 선택지의 차이가 {CLOSE_CHOICE_MARGIN:g}%p 이하예요.",
        ))
    set_min = 100 * best.get("set_min", best["win"])
    set_max = 100 * best.get("set_max", best["win"])
    if set_max - set_min >= SET_SENSITIVITY_MARGIN:
        notes.append((
            "상대 세트에 민감",
            f"가능한 상대 세트 조합에 따라 이 선택의 예상 승률은 {set_min:.1f}~{set_max:.1f}%예요.",
        ))
    if notes:
        st.html("".join(
            f'<div class="decision-note" role="note"><strong>{esc(title)}</strong>'
            f'<span>{esc(message)}</span></div>'
            for title, message in notes
        ))
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


def opponent_panels(rows, catalog, specified):
    st.subheader("상대 선봉 세트")
    if not rows:
        st.info("공개된 정보에 맞는 세트가 등록되어 있지 않아요.")
        return
    cards = []
    for row in sorted(rows, key=lambda item: item["probability"], reverse=True):
        probability = 100 * row["probability"]
        weight_label = "직접 지정" if specified else f"{probability:.0f}%"
        item = localized(catalog, row.get("item"), "item")
        ability = localized(catalog, row.get("battle_ability") or row.get("ability"), "ability")
        moves = "".join(
            f'<span class="move-chip">{esc(localized(catalog, move, "move"))}</span>'
            for move in row["moves"]
        )
        cards.append(
            f'<div class="set-card"><div class="set-title"><strong>{esc(set_name(row))}</strong>'
            f'<span>{weight_label}</span></div><div class="set-detail">{esc(item)} · {esc(ability)}</div>'
            f'<div class="set-moves">{moves}</div></div>'
        )
    st.html('<div class="sets">' + "".join(cards) + "</div>")
    if specified:
        st.caption("직접 지정한 선봉 세트를 100% 반영한 결과예요.")
    else:
        st.caption("사용률 통계에서 구성한 선봉 후보의 추정 비중이에요. 공개된 정보와 팀의 도구 중복 제한을 반영해요.")


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
            close_cases = summary.get("observed_40_60")
            if close_cases and close_cases["cases"]:
                st.caption(
                    f'시뮬레이션 승률 40~60%인 대면 {close_cases["cases"]}개에서는 '
                    f'평균 {100 * close_cases["probability_mae"]:.1f}%p 차이가 났어요.'
                )


def change_preset(case):
    for key in list(st.session_state):
        if key.startswith(("아군-", "상대-", "revealed-", "weather", "mode")):
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
                own_active = active_controls("아군", entries, catalog, own_start[0], weather)
                own = [own_active]
                if mode == "team":
                    with st.expander("아군 교체 후보"):
                        own = bench_controls("아군", own_active, entries, catalog, own_start, predictor.catalog.compatible_sets)
            with right:
                foe_active = active_controls("상대", entries, catalog, foe_start[0], weather)
                foe = [foe_active]
                if mode == "team":
                    with st.expander("상대 대기 포켓몬과 세트"):
                        foe = bench_controls("상대", foe_active, entries, catalog, foe_start, predictor.catalog.compatible_sets)
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
                opponent_panels(inferred, catalog, specified=foe_active["set"] is not None)
            source = catalog["source"]
            species_count = len({base_species(entry) for entry in entries.values()})
            st.caption(
                f'{species_count}종 · 레벨 50 · [레귤레이션 M-C]({source["rules_url"]}) · '
                f'[Showdown 사용률 {source["month"]}]({source["usage_url"]})'
            )
    with eval_tab:
        evaluation()


if __name__ == "__main__":
    main()
