"""임상시험 매칭 멀티 에이전트 — Streamlit 데모 (로드맵 6단계).

실행: streamlit run app.py
필요: .env 의 ANTHROPIC_API_KEY

화면 흐름:
  1. 환자 선택(S001~S010) 또는 직접 입력 → [분석 시작]
  2. 프로필 → 후보 검색(하드 필터) → 시험별 스크리닝 시트 → 추천 순위
  3. 질문 루프: 여러 시험에 공통으로 필요한 정보부터 질문(next_round) → 답하면 관련 기준만 재판정(reassess)
     → 판정 변화(이전→이후) 표시 → "질문 끝내기"로 전체 재판정 한 번(final_check)
"""

import hashlib
import json
from pathlib import Path

import streamlit as st

from src.agents.recommender import rank_trials
from src.pipeline import all_answers, final_check, next_round, reassess, run_intake
from src.question_builder import questions_for_round
from src import ui

ROOT = Path(__file__).resolve().parent

# 디자인은 src/ui.py (Ada 색감 + Abridge풍 라인 아이콘). 아래 두 dict는 일반 텍스트 자리용.
VERDICT_KO = {"pass": "통과", "fail": "탈락", "unknown": "모름", "post_enrollment": "등록 후 확인"}
FINAL_KO = ui.LABEL

st.set_page_config(page_title="임상시험 매칭 에이전트", page_icon="🩺", layout="wide")
ui.inject_css()
ui.header()


@st.cache_data
def load_patients() -> dict:
    data = json.loads((ROOT / "data" / "raw" / "official_synthetic_patients.json").read_text(encoding="utf-8"))
    return {t["num"]: t["title"] for t in data["topics"]}


def render_screening(s: dict, prev_judgments: list[dict] | None = None) -> None:
    """스크리닝 시트 표 렌더링 (재평가면 바뀐 판정에 이전→이후 표시)."""
    prev_by_id = {j["criterion_id"]: j for j in (prev_judgments or [])}
    crit_by_id = {c["id"]: c for c in s["criteria"]}
    rows = []
    for j in s["judgments"]:
        c = crit_by_id.get(j["criterion_id"], {})
        prev = prev_by_id.get(j["criterion_id"])
        if prev and prev["verdict"] != j["verdict"]:
            verdict_html = ui.change(prev["verdict"], j["verdict"])
        else:
            verdict_html = ui.badge(j["verdict"])
        rows.append({
            "id": j["criterion_id"],
            "kind": "선정" if c.get("type") == "inclusion" else "제외",
            "text": c.get("text", "")[:80],
            "verdict_html": verdict_html,
            "evidence": j["evidence"][:120],
        })
    st.markdown(ui.screening_table(rows), unsafe_allow_html=True)


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
        case_text = st.text_area("환자 케이스 (영어)", height=120,
                                 placeholder="A 45-year-old man with ...")
        # run_intake는 환자 ID별로 프로필을 저장해 다시 쓴다 → 직접 입력은 설명 내용별로 ID를 달리해서
        # 다른 환자의 저장된 프로필을 가져다 쓰지 않게
        pid = "CUSTOM_" + hashlib.sha1(case_text.strip().encode("utf-8")).hexdigest()[:8]
    max_candidates = st.slider("스크리닝할 후보 시험 수", 1, 5, 3,
                               help="많을수록 정확하지만 LLM 비용과 시간이 늘어납니다")
    st.divider()
    start = st.button("분석 시작", type="primary", icon=":material/search:",
                      disabled=not case_text.strip())
    if st.button("초기화", icon=":material/restart_alt:"):
        st.session_state.clear()
        st.rerun()
    st.divider()
    # API 없이 저장된 결과로 화면만 보는 모드 (디자인 확인·발표 리허설용)
    if st.button("예시 결과 미리보기 (S005)", icon=":material/visibility:",
                 help="data/handoff/S005.json 저장본을 불러와요 — API 호출 없음"):
        example = json.loads((ROOT / "data" / "handoff" / "S005.json").read_text(encoding="utf-8"))
        st.session_state.clear()
        st.session_state.update(bundle=example, prev_judgments={},
                                last_changed=[], finished=False, preview=True)
        st.rerun()

shown_case = st.session_state.get("bundle", {}).get("case_text") or case_text
st.markdown(f"> **환자 케이스:** {shown_case}" if shown_case.strip() else "_왼쪽에서 환자를 선택하세요._")
if st.session_state.get("preview"):
    st.info("예시 모드 — 저장된 S005 결과를 보여주고 있어요. 질문 생성은 무료 모드로 돌고, 재평가는 API가 필요해 비활성화됩니다.")

# ── 1차 분석: 1~4번은 팀 표준 진입점 run_intake 하나로 (10/20 합의) ───────
if start:
    st.session_state.clear()
    with st.status("에이전트 파이프라인 실행 중...", expanded=True) as status:
        # save=False: 데모 실행이 data/handoff/의 커밋된 예시 파일을 덮어쓰지 않게
        bundle = run_intake(case_text, patient_id=pid, max_candidates=max_candidates,
                            save=False, on_step=st.write)
        status.update(label="분석 완료", state="complete")
    # 질문 루프는 bundle(handoff 형식) 하나에 질문·답변·바뀐 판정을 쌓는다 (docs/질문루프_정리.md)
    st.session_state.update(bundle=bundle, prev_judgments={}, last_changed=[], finished=False)

# ── 결과 표시 ───────────────────────────────────────────────
if "bundle" in st.session_state:
    bundle = st.session_state["bundle"]
    screenings = bundle["trials"]

    with st.expander("구조화된 환자 프로필", expanded=False):
        st.json(bundle["profile"])
    if not screenings:   # 검색·나이·성별 필터 후 후보가 없으면 판정표·질문이 없음 (st.tabs([])는 오류)
        st.warning("조건(나이·성별)에 맞는 후보 시험을 찾지 못했어요. 환자 설명을 바꾸거나 후보 수를 늘려 보세요.")
        st.stop()

    ranking = rank_trials(screenings)
    ui.section("추천 순위", "pulse")
    for i, s in enumerate(ranking["recommended"], 1):
        counts = {}
        for j in s["judgments"]:
            counts[j["verdict"]] = counts.get(j["verdict"], 0) + 1
        st.markdown(ui.rank_card(f"{i}위", s["nct_id"], s["title"][:90],
                                 s["final_judgment"], counts), unsafe_allow_html=True)
    for s in ranking["excluded"]:
        fails = [j["criterion_id"] for j in s["judgments"] if j["verdict"] == "fail"]
        st.markdown(ui.rank_card("제외", s["nct_id"], s["title"][:90],
                                 "ineligible", {"fail_ids": fails}), unsafe_allow_html=True)

    if st.session_state["last_changed"]:
        ui.section("바뀐 판정 (방금 반영)", "check")
        for c in st.session_state["last_changed"]:
            src = "전체 재판정" if c["source"] == ["full"] else ", ".join(c["source"]) + " 답변"
            st.markdown(f'**{c["trial"]} {c["criterion_id"]}** &nbsp;{ui.change(c["from"], c["to"])}'
                        f' <span style="color:#64748F;font-size:0.84rem;">(근거: {src})</span>',
                        unsafe_allow_html=True)

    ui.section("시험별 스크리닝 시트", "doc")
    tabs = st.tabs([s["nct_id"] for s in screenings])
    prev_map = st.session_state.get("prev_judgments", {})
    for tab, s in zip(tabs, screenings):
        with tab:
            st.markdown(f'**{s["title"]}**&ensp;{ui.badge(s["final_judgment"], large=True)}',
                        unsafe_allow_html=True)
            render_screening(s, prev_map.get(s["nct_id"]))

    if bundle.get("rounds"):
        with st.expander("질문·답변 기록", expanded=False):
            for a in all_answers(bundle):
                st.markdown(f"**{a['id']}. {a['question']}**  \n→ {a['answer']}")

    def snapshot() -> dict:
        return {s["nct_id"]: [dict(j) for j in s["judgments"]] for s in screenings}

    # ── 질문 루프: [5] next_round → 환자 답변 → [6] reassess → ... → 끝내면 final_check ──
    if st.session_state["finished"]:
        st.success("질문을 마치고 전체 재판정까지 끝났습니다. 위 판정이 최종 결과입니다.")
    else:
        if "pending" not in st.session_state:
            # 예시 모드는 무료 묶기(use_llm=False)로 질문을 만든다 (API 불필요)
            qfn = ((lambda b, max_questions=5: questions_for_round(b, max_questions, use_llm=False))
                   if st.session_state.get("preview") else None)
            with st.spinner("[5] 질문 생성 에이전트 (여러 시험에 공통으로 필요한 정보부터)..."):
                st.session_state["pending"] = next_round(bundle, build_questions=qfn)
        questions = st.session_state["pending"]
        if questions:
            ui.section(f"확인 질문 (라운드 {bundle['rounds'][-1]['round']})", "chat")
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
                if st.session_state.get("preview"):
                    st.warning("예시 모드에서는 재평가(LLM 호출)를 할 수 없어요. 실제 분석에서 사용해주세요.")
                elif not filled:
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

        if bundle.get("rounds") and st.button("질문 끝내기 (전체 재판정)", icon=":material/done_all:",
                                              disabled=bool(st.session_state.get("preview")),
                                              help="모든 기준을 원문 + 모든 답변으로 한 번 더 판정합니다"):
            prev = snapshot()
            with st.spinner("전체 재판정 중..."):
                changed = final_check(bundle)
            st.session_state.update(prev_judgments=prev, last_changed=changed, finished=True, draft={}, q_index=0)
            st.session_state.pop("pending", None)
            st.rerun()
