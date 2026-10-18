"""임상시험 매칭 멀티 에이전트 — Streamlit 데모 (로드맵 6단계).

실행: streamlit run app.py
필요: .env 의 ANTHROPIC_API_KEY

화면 흐름:
  1. 환자 선택(S001~S010) 또는 직접 입력 → [분석 시작]
  2. 프로필 → 후보 검색(하드 필터) → 시험별 스크리닝 시트 → 추천 순위
  3. 질문 루프: 여러 시험에 공통으로 필요한 정보부터 질문(next_round) → 답하면 관련 기준만 재판정(reassess)
     → 판정 변화(이전→이후) 표시 → "질문 끝내기"로 전체 재판정 한 번(final_check)
"""

import json
from pathlib import Path

import streamlit as st

from src.agents.criteria_parser import parse_criteria
from src.agents.matcher import final_judgment, match_with_rules
from src.agents.patient_profiler import profile_patient
from src.agents.recommender import rank_trials
from src.agents.trial_searcher import search_candidates
from src.pipeline import all_answers, final_check, next_round, reassess

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
    judgments, _ = match_with_rules(profile, criteria, case_text=case_text)
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
    # 질문 루프는 bundle(handoff 형식) 하나에 질문·답변·바뀐 판정을 쌓는다 (docs/질문루프_정리.md)
    bundle = {"patient_id": pid, "case_text": case_text, "profile": profile, "trials": screenings}
    st.session_state.update(bundle=bundle, search=search, prev_judgments={}, last_changed=[], finished=False)

# ── 결과 표시 ───────────────────────────────────────────────
if "bundle" in st.session_state:
    bundle = st.session_state["bundle"]
    screenings = bundle["trials"]

    with st.expander("🧑‍⚕️ 구조화된 환자 프로필", expanded=False):
        st.json(bundle["profile"])

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

    if st.session_state["last_changed"]:
        st.subheader("바뀐 판정 (방금 반영)")
        for c in st.session_state["last_changed"]:
            src = "전체 재판정" if c["source"] == ["full"] else ", ".join(c["source"]) + " 답변"
            st.markdown(f"- **{c['trial']} {c['criterion_id']}**: {VERDICT_KO.get(c['from'], c['from'])} → "
                        f"{VERDICT_KO.get(c['to'], c['to'])} (근거: {src})")

    st.subheader("시험별 스크리닝 시트")
    tabs = st.tabs([s["nct_id"] for s in screenings])
    prev_map = st.session_state.get("prev_judgments", {})
    for tab, s in zip(tabs, screenings):
        with tab:
            st.markdown(f"**{s['title']}** — {FINAL_KO[s['final_judgment']]}")
            render_screening(s, prev_map.get(s["nct_id"]))

    if bundle.get("rounds"):
        with st.expander("🗒️ 질문·답변 기록", expanded=False):
            for a in all_answers(bundle):
                st.markdown(f"**{a['id']}. {a['question']}**  \n→ {a['answer']}")

    def snapshot() -> dict:
        return {s["nct_id"]: [dict(j) for j in s["judgments"]] for s in screenings}

    # ── 질문 루프: [5] next_round → 환자 답변 → [6] reassess → ... → 끝내면 final_check ──
    if st.session_state["finished"]:
        st.success("질문을 마치고 전체 재판정까지 끝났습니다. 위 판정이 최종 결과입니다.")
    else:
        if "pending" not in st.session_state:
            with st.spinner("[5] 질문 생성 에이전트 (여러 시험에 공통으로 필요한 정보부터)..."):
                st.session_state["pending"] = next_round(bundle)
        questions = st.session_state["pending"]
        if questions:
            st.subheader(f"💬 확인 질문 (라운드 {bundle['rounds'][-1]['round']})")
            st.caption("질문을 하나씩 보여 줘요. 모르면 비워 두고 '다음'을 누르세요. 답은 마지막에 한 번에 반영해요 "
                       "(답하지 않은 질문은 다음 라운드에 다시 묻지 않아요).")
            # 한 번에 한 질문: 답은 draft에 모았다가 마지막 버튼에서 한 번에 재판정 (호출 수는 그대로)
            # 폼을 쓰지 않아서 입력 칸에서 엔터를 눌러도 제출되지 않는다
            draft = st.session_state.setdefault("draft", {})
            i = min(st.session_state.setdefault("q_index", 0), len(questions) - 1)
            q = questions[i]
            key = f"a_{q['id']}"
            if key not in st.session_state:          # 보이지 않는 입력 칸은 지워지므로 draft에서 되살림
                st.session_state[key] = draft.get(q["id"], "")

            def move(step: int) -> None:
                draft[q["id"]] = st.session_state[key]
                st.session_state["q_index"] = i + step

            st.progress((i + 1) / len(questions), text=f"질문 {i + 1} / {len(questions)}")
            related = ", ".join(f"{r['trial']} {'·'.join(r['criteria'])}" for r in q["resolves"])
            st.text_input(f"{q['id']}. {q['text']}", key=key, help=f"관련 기준: {related}")
            left, right, _ = st.columns([1, 2, 3])
            left.button("← 이전", on_click=move, args=(-1,), disabled=i == 0)
            last = i == len(questions) - 1
            submitted = right.button("답변 반영 후 재평가" if last else "다음 →", type="primary",
                                     on_click=move, args=(0 if last else 1,)) and last
            done = [x["id"] for x in questions if draft.get(x["id"], "").strip()]
            if done:
                st.caption(f"답한 질문: {', '.join(done)}")
            if submitted:
                filled = [{"question_id": x["id"], "answer": draft[x["id"]]} for x in questions
                          if draft.get(x["id"], "").strip()]
                if not filled:
                    st.warning("답변을 하나 이상 입력해주세요.")
                else:
                    prev = snapshot()
                    with st.spinner("[6] 답과 관련된 기준만 다시 판정..."):
                        changed = reassess(bundle, filled)
                    st.session_state.update(prev_judgments=prev, last_changed=changed, draft={}, q_index=0)
                    del st.session_state["pending"]
                    st.rerun()
        else:
            st.info("더 물어볼 '모름' 기준이 없습니다. 질문을 끝내고 전체 재판정을 해 주세요.")

        if bundle.get("rounds") and st.button("질문 끝내기 (전체 재판정)",
                                              help="모든 기준을 원문 + 모든 답변으로 한 번 더 판정합니다"):
            prev = snapshot()
            with st.spinner("전체 재판정 중..."):
                changed = final_check(bundle)
            st.session_state.update(prev_judgments=prev, last_changed=changed, finished=True, draft={}, q_index=0)
            st.session_state.pop("pending", None)
            st.rerun()
