"""임상시험 매칭 멀티 에이전트 — Streamlit 데모 (로드맵 6단계).

실행: streamlit run app.py
필요: .env 의 ANTHROPIC_API_KEY

화면 흐름:
  1. 환자 선택(S001~S010) 또는 직접 입력 → [분석 시작]
  2. 프로필 → 후보 검색(하드 필터) → 시험별 스크리닝 시트 → 추천 순위
  3. "모름" 기준에 대한 확인 질문에 답하면 → 재평가 → 판정 변화(이전→이후) 표시
"""

import json
from pathlib import Path

import streamlit as st

from src.agents.criteria_parser import parse_criteria
from src.agents.matcher import final_judgment, match
from src.agents.patient_profiler import profile_patient
from src.agents.profile_updater import update_profile
from src.agents.question_generator import generate_questions
from src.agents.recommender import rank_trials
from src.agents.trial_searcher import search_candidates

ROOT = Path(__file__).resolve().parent

VERDICT_KO = {"pass": "✅ 통과", "fail": "❌ 탈락", "unknown": "❓ 모름", "post_enrollment": "🕒 등록 후 확인"}
FINAL_KO = {
    "eligible": "🟢 적격",
    "probably_eligible": "🟡 적격 가능 (등록 후 확인 필요)",
    "insufficient_info": "🟠 정보 부족 (확인 질문 필요)",
    "ineligible": "🔴 부적격",
}

st.set_page_config(page_title="임상시험 매칭 에이전트", page_icon="🏥", layout="wide")
st.title("🏥 인터랙티브 임상시험 추천 에이전트")
st.caption("※ 본 시스템의 출력은 의학적 자문이 아닌 연구·참고용입니다. 실제 임상시험 참여는 반드시 의료진과 상의하세요.")


@st.cache_data
def load_patients() -> dict:
    data = json.loads((ROOT / "data" / "raw" / "official_synthetic_patients.json").read_text(encoding="utf-8"))
    return {t["num"]: t["title"] for t in data["topics"]}


def get_criteria_cached(trial: dict) -> list[dict]:
    """기준 파싱 (디스크 캐시 재사용 — 데모 중 반복 비용 절약)."""
    path = ROOT / "data" / "processed" / f"criteria_{trial['nct_id']}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    criteria = parse_criteria(trial["eligibility_criteria"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(criteria, ensure_ascii=False, indent=2), encoding="utf-8")
    return criteria


def screen_trial(profile: dict, trial: dict, case_text: str | None = None) -> dict:
    criteria = get_criteria_cached(trial)
    judgments = match(profile, criteria, case_text=case_text)
    return {
        "nct_id": trial["nct_id"],
        "title": trial["title"],
        "criteria": criteria,
        "judgments": judgments,
        "final_judgment": final_judgment(judgments),
    }


def render_screening(s: dict, prev_judgments: list[dict] | None = None) -> None:
    """스크리닝 시트 표 렌더링 (재평가면 바뀐 판정에 이전→이후 표시)."""
    prev_by_id = {j["criterion_id"]: j for j in (prev_judgments or [])}
    crit_by_id = {c["id"]: c for c in s["criteria"]}
    rows = []
    for j in s["judgments"]:
        c = crit_by_id.get(j["criterion_id"], {})
        verdict = VERDICT_KO.get(j["verdict"], j["verdict"])
        prev = prev_by_id.get(j["criterion_id"])
        if prev and prev["verdict"] != j["verdict"]:
            verdict = f"{VERDICT_KO.get(prev['verdict'], '')} → {verdict}"
        rows.append({
            "ID": j["criterion_id"],
            "구분": "선정" if c.get("type") == "inclusion" else "제외",
            "기준": c.get("text", "")[:80],
            "판정": verdict,
            "근거": j["evidence"][:120],
        })
    st.dataframe(rows, width="stretch", hide_index=True)


# ── 사이드바: 입력 ──────────────────────────────────────────
patients = load_patients()
with st.sidebar:
    st.header("환자 입력")
    mode = st.radio("입력 방식", ["예시 환자 (S001~S010)", "직접 입력"])
    if mode == "예시 환자 (S001~S010)":
        pid = st.selectbox("환자 선택", list(patients.keys()),
                           format_func=lambda p: f"{p} — {patients[p][:40]}...")
        case_text = patients[pid]
    else:
        pid = "CUSTOM"
        case_text = st.text_area("환자 케이스 (영어)", height=120,
                                 placeholder="A 45-year-old man with ...")
    max_candidates = st.slider("스크리닝할 후보 시험 수", 1, 5, 3,
                               help="많을수록 정확하지만 LLM 비용과 시간이 늘어납니다")
    st.divider()
    start = st.button("🔍 분석 시작", type="primary", disabled=not case_text.strip())
    if st.button("초기화"):
        st.session_state.clear()
        st.rerun()

st.markdown(f"> **환자 케이스:** {case_text}" if case_text.strip() else "_왼쪽에서 환자를 선택하세요._")

# ── 1차 분석 ────────────────────────────────────────────────
if start:
    st.session_state.clear()
    with st.status("에이전트 파이프라인 실행 중...", expanded=True) as status:
        st.write("[1] 환자 정보 이해 에이전트...")
        profile = profile_patient(case_text)
        profile["id"] = pid
        st.write("[2] 후보 검색 + 하드 필터(나이·성별)...")
        search = search_candidates(profile, max_candidates=max_candidates)
        st.write(f"    검색어 {search['queries']} → {search['total_found']}건 → 필터 후 {search['after_hard_filter']}건")
        screenings = []
        for i, trial in enumerate(search["candidates"], 1):
            st.write(f"[3-4] {trial['nct_id']} 기준 파싱 + 매칭 ({i}/{len(search['candidates'])})...")
            screenings.append(screen_trial(profile, trial, case_text))
        status.update(label="분석 완료", state="complete")
    st.session_state.update(profile=profile, search=search, screenings=screenings, round=1, case_text=case_text,
                            prev_judgments={})

# ── 결과 표시 ───────────────────────────────────────────────
if "screenings" in st.session_state:
    profile = st.session_state["profile"]
    screenings = st.session_state["screenings"]

    with st.expander("🧑‍⚕️ 구조화된 환자 프로필", expanded=False):
        st.json(profile)

    ranking = rank_trials(screenings)
    st.subheader("추천 순위")
    for i, s in enumerate(ranking["recommended"], 1):
        counts = {}
        for j in s["judgments"]:
            counts[j["verdict"]] = counts.get(j["verdict"], 0) + 1
        st.markdown(f"**{i}위. {s['nct_id']}** — {FINAL_KO[s['final_judgment']]} "
                    f"(통과 {counts.get('pass', 0)} · 모름 {counts.get('unknown', 0)} · "
                    f"등록 후 확인 {counts.get('post_enrollment', 0)})  \n{s['title'][:90]}")
    for s in ranking["excluded"]:
        fails = [j["criterion_id"] for j in s["judgments"] if j["verdict"] == "fail"]
        st.markdown(f"**제외. {s['nct_id']}** — {FINAL_KO['ineligible']} (탈락 기준: {', '.join(fails)})")

    st.subheader("시험별 스크리닝 시트")
    tabs = st.tabs([s["nct_id"] for s in screenings])
    prev_map = st.session_state.get("prev_judgments", {})
    for tab, s in zip(tabs, screenings):
        with tab:
            st.markdown(f"**{s['title']}** — {FINAL_KO[s['final_judgment']]}")
            render_screening(s, prev_map.get(s["nct_id"]))

    # ── 질문 루프 ───────────────────────────────────────────
    needs_info = [s for s in screenings if s["final_judgment"] == "insufficient_info"]
    if needs_info:
        st.subheader(f"💬 확인 질문 (라운드 {st.session_state['round']})")
        target = needs_info[0]  # 추천 1순위 후보부터 질문
        if "questions" not in st.session_state:
            with st.spinner("[5] 질문 생성 에이전트..."):
                st.session_state["questions"] = generate_questions(target["criteria"], target["judgments"])
                st.session_state["question_target"] = target["nct_id"]
        questions = st.session_state["questions"]
        st.caption(f"대상 시험: {st.session_state['question_target']} — 답을 아는 것만 적어도 됩니다.")

        with st.form("qa_form"):
            answers = [st.text_input(f"Q{i}. {q['question']}", key=f"q{st.session_state['round']}_{i}")
                       for i, q in enumerate(questions, 1)]
            submitted = st.form_submit_button("답변 반영 후 재평가", type="primary")

        if submitted:
            qa_pairs = [{"question": q["question"], "answer": a}
                        for q, a in zip(questions, answers) if a.strip()]
            if not qa_pairs:
                st.warning("답변을 하나 이상 입력해주세요.")
            else:
                with st.status("재평가 중...", expanded=True) as status:
                    st.write("[5b] 프로필 갱신...")
                    profile = update_profile(profile, qa_pairs)
                    st.write("[4] 전체 시험 재평가...")
                    prev = {s["nct_id"]: s["judgments"] for s in screenings}
                    screenings = [
                        {**s, "judgments": (new_j := match(profile, s["criteria"], case_text=st.session_state.get("case_text"))),
                         "final_judgment": final_judgment(new_j)}
                        for s in screenings
                    ]
                    status.update(label="재평가 완료", state="complete")
                st.session_state.update(profile=profile, screenings=screenings,
                                        prev_judgments=prev, round=st.session_state["round"] + 1)
                del st.session_state["questions"]
                st.rerun()
    else:
        st.success("모든 시험의 판정이 확정되었습니다 (남은 확인 질문 없음).")
