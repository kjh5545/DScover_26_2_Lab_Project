"""인선 상세 환자로 새 환자 검증 (판정 v3 규칙을 만들 때 보지 않은 데이터).

실행: python scripts/eval_detailed.py --check   # 무료: 시트 읽기·점검만 (빈 판정, 이상한 값, 최종 판단 계산과 다른지)
      python scripts/eval_detailed.py           # A. 상세 설명으로 바로 판정 → 인선 정답과 비교 (비용 발생)
      python scripts/eval_detailed.py --loop    # A + B. 짧은 설명에서 시작해 질문 루프 → 정답과 비교 (비용 발생)
      옵션: 시트 경로를 주면 그 시트만 (기본: screening/detailed/*/*.md 중 채워진 것), --rounds N (B 라운드 수, 기본 3)

A. 정보가 다 있을 때 판정을 잘하나: 상세 설명 → 1번 프로필 → v3 판정(+코드 판정·출력 검사) → 기준별로 정답과 비교.
   핵심 숫자는 "정답이 통과·탈락인 기준을 맞힌 수" (평가 세트는 정답 71%가 모름이라 이걸 거의 못 쟀음)
B. 1위 팀 방식(가린 정보를 질문으로 되찾기): 짧은 원래 설명의 v3 판정에서 시작 → 질문 → 시뮬레이터가 상세 설명만 보고
   답변 → 관련 기준 재판정 → 마지막 전체 재판정. 루프 전·후 정답 일치와 모름 수를 비교.
비용(Sonnet 5.5, 환자 1명·시험 2개 기준): A 약 $0.03~0.06 (프로필 1 + 판정 2), B 약 $0.1~0.3. 끝에 실제 비용 출력.
A의 프로필·판정은 상세 설명 내용별로 저장해 다시 돌릴 때 재사용 (시트의 상세 설명을 고치면 새로 판정).
"""

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.agents.matcher import final_judgment, match_with_rules  # noqa: E402
from src.llm import spent  # noqa: E402
from src.testing.detailed_sheet import is_filled, parse_sheet  # noqa: E402

OUT = ROOT / "data" / "processed" / "detailed_eval"
KO = {"pass": "통과", "fail": "탈락", "unknown": "모름", "post_enrollment": "등록 후 확인", None: "(없음)"}
FINAL_KO = {"eligible": "적격", "probably_eligible": "적격 가능", "insufficient_info": "정보 부족",
            "ineligible": "부적격", None: "(없음)"}
ORDER = ["pass", "fail", "unknown", "post_enrollment"]


def gold_of(sheet: dict) -> dict:
    return {(t["nct_id"], r["id"]): r for t in sheet["trials"] for r in t["rows"] if r["verdict"]}


def check(sheet: dict) -> None:
    """무료 점검: 읽은 내용 요약 + 문제 + 인선 최종 판단이 기준별 판정으로 계산한 값과 같은지."""
    print(f"\n[{sheet['patient_id']}] {sheet['path']} (작성: {sheet['author']})")
    print(f"  상세 설명 {len(sheet['detailed_text'])}자, 메모 {len(sheet['memo'])}줄")
    for t in sheet["trials"]:
        c = Counter(KO[r["verdict"]] for r in t["rows"])
        computed = final_judgment([{"verdict": r["verdict"]} for r in t["rows"] if r["verdict"]])
        note = "" if t["final"] in (None, computed) else f"  ← 기준별 판정으로 계산하면 {FINAL_KO[computed]}"
        print(f"  {t['nct_id']}: {dict(c)} / 최종 판단 {FINAL_KO[t['final']]}{note}")
    for p in sheet["problems"]:
        print(f"  ⚠ {p}")


def compare(label: str, gold: dict, judged: dict[str, list[dict]]) -> dict:
    """기준별 비교 → 요약 숫자와 불일치 목록 (judged: {시험: 판정 목록})."""
    pairs = []
    for nct, js in judged.items():
        for j in js:
            g = gold.get((nct, j["criterion_id"]))
            if g:
                pairs.append((nct, j, g))
    same = sum(j["verdict"] == g["verdict"] for _, j, g in pairs)
    decided = [(n, j, g) for n, j, g in pairs if g["verdict"] in ("pass", "fail")]
    decided_ok = sum(j["verdict"] == g["verdict"] for _, j, g in decided)
    confusion = Counter((g["verdict"], j["verdict"]) for _, j, g in pairs)
    print(f"\n  == {label} ==")
    print(f"  기준 일치: {same}/{len(pairs)}")
    print(f"  정답이 통과·탈락인 기준: {decided_ok}/{len(decided)} 맞힘"
          f" (통과 {sum(j['verdict'] == g['verdict'] for _, j, g in decided if g['verdict'] == 'pass')}"
          f"/{sum(g['verdict'] == 'pass' for _, _, g in decided)},"
          f" 탈락 {sum(j['verdict'] == g['verdict'] for _, j, g in decided if g['verdict'] == 'fail')}"
          f"/{sum(g['verdict'] == 'fail' for _, _, g in decided)})")
    print("  혼동표 (행: 정답, 열: AI)  " + "  ".join(f"{KO[v]:>6}" for v in ORDER))
    for gv in ORDER:
        if any(confusion[(gv, av)] for av in ORDER):
            print(f"  {KO[gv]:>24}  " + "  ".join(f"{confusion[(gv, av)]:>6}" for av in ORDER))
    misses = [{"trial": n, "id": j["criterion_id"], "gold": g["verdict"], "ai": j["verdict"],
               "ai_evidence": j.get("evidence", ""), "gold_evidence": g["evidence"]}
              for n, j, g in pairs if j["verdict"] != g["verdict"]]
    for m in misses:
        print(f"  [{m['trial']} {m['id']}] 정답={KO[m['gold']]} vs AI={KO[m['ai']]}")
        print(f"     AI 근거: {m['ai_evidence'][:160]}")
        if m["gold_evidence"]:
            print(f"     정답 근거: {m['gold_evidence'][:160]}")
    return {"same": same, "total": len(pairs), "decided_ok": decided_ok, "decided": len(decided),
            "confusion": {f"{g}->{a}": n for (g, a), n in confusion.items()}, "misses": misses}


def finals(label: str, sheet: dict, judged: dict[str, list[dict]]) -> list[dict]:
    out = []
    for t in sheet["trials"]:
        ai = final_judgment(judged[t["nct_id"]]) if t["nct_id"] in judged else None
        out.append({"trial": t["nct_id"], "gold": t["final"], "ai": ai})
        print(f"  최종 판단 {t['nct_id']}: 정답 {FINAL_KO[t['final']]} / {label} {FINAL_KO[ai]}"
              f" {'✔' if ai == t['final'] else '✘'}")
    return out


def run_direct(sheet: dict) -> dict:
    """A. 상세 설명으로 바로 판정."""
    from src.pipeline import understand_patient
    from src.testing.goldset_bundle import make_bundle

    pid = sheet["patient_id"]
    key = f"{pid}_detailed_{hashlib.sha1(sheet['detailed_text'].encode('utf-8')).hexdigest()[:8]}"
    profile = understand_patient(sheet["detailed_text"], patient_id=key)   # 같은 설명이면 저장된 것 사용
    criteria = {t["nct_id"]: t["criteria"] for t in make_bundle(pid)["trials"]}
    judged = {}
    for t in sheet["trials"]:
        cache = OUT / f"{key}_{t['nct_id']}.json"
        if cache.exists():
            judged[t["nct_id"]] = json.loads(cache.read_text(encoding="utf-8"))
            continue
        js, _ = match_with_rules(profile, criteria[t["nct_id"]], case_text=sheet["detailed_text"])
        cache.write_text(json.dumps(js, ensure_ascii=False, indent=2), encoding="utf-8")
        judged[t["nct_id"]] = js
    result = compare("A. 상세 설명으로 바로 판정", gold_of(sheet), judged)
    result["finals"] = finals("AI", sheet, judged)
    return result


def run_loop(sheet: dict, rounds: int) -> dict:
    """B. 짧은 설명에서 시작 → 질문 루프 (시뮬레이터는 상세 설명만 보고 답함) → 마지막 전체 재판정."""
    from src.pipeline import final_check, next_round, reassess
    from src.testing.goldset_bundle import make_bundle
    from src.testing.patient_simulator import answer_questions

    gold = gold_of(sheet)
    bundle = make_bundle(sheet["patient_id"])
    snapshot = lambda: {t["nct_id"]: [dict(j) for j in t["judgments"]] for t in bundle["trials"]}  # noqa: E731
    n_unknown = lambda: sum(j["verdict"] == "unknown" for t in bundle["trials"] for j in t["judgments"])  # noqa: E731
    before = compare("B-0. 짧은 설명 (루프 전)", gold, snapshot())
    unknown_before = n_unknown()

    asked = 0
    for _ in range(rounds):
        questions = next_round(bundle, max_questions=5)
        if not questions:
            break
        asked += len(questions)
        qa = answer_questions(sheet["detailed_text"], [{"question": q["text"]} for q in questions])
        answers = [{"question_id": q["id"], "answer": a["answer"]} for q, a in zip(questions, qa)]
        print(f"\n  ── 라운드 {bundle['rounds'][-1]['round']} ──")
        for q, a in zip(questions, answers):
            print(f"  {q['id']}. {q['text']}\n      → {a['answer']}")
        for c in reassess(bundle, answers):
            g = gold.get((c["trial"], c["criterion_id"]), {}).get("verdict")
            print(f"     {c['trial']} {c['criterion_id']}: {KO[c['from']]} → {KO[c['to']]}"
                  f" (정답 {KO[g]}{' ✔' if c['to'] == g else ''})")
    fixes = final_check(bundle)
    print(f"\n  마지막 전체 재판정: 바뀐 판정 {len(fixes)}개")
    for c in fixes:
        print(f"     {c['trial']} {c['criterion_id']}: {KO[c['from']]} → {KO[c['to']]}")

    after = compare("B-1. 질문 루프 + 전체 재판정 후", gold, snapshot())
    after["finals"] = finals("루프 후", sheet, snapshot())
    print(f"\n  질문 {asked}개 → 모름 {unknown_before} → {n_unknown()}")
    (OUT / f"{sheet['patient_id']}_loop.json").write_text(json.dumps(bundle, ensure_ascii=False, indent=2),
                                                         encoding="utf-8")
    return {"before": before, "after": after, "questions": asked,
            "unknown_before": unknown_before, "unknown_after": n_unknown()}


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    rounds = 3
    if "--rounds" in sys.argv:
        rounds = int(sys.argv[sys.argv.index("--rounds") + 1])
        args = [a for a in args if a != str(rounds)]
    paths = [Path(a) for a in args] or sorted((ROOT / "screening" / "detailed").glob("*/*_detailed_sheet*.md"))
    sheets = [parse_sheet(p) for p in paths]
    filled = [s for s in sheets if is_filled(s)]
    print(f"시트 {len(sheets)}개 중 채워진 시트 {len(filled)}개: {[s['patient_id'] for s in filled]}")

    for s in filled:
        check(s)
    if "--check" in sys.argv or not filled:
        return 0

    OUT.mkdir(parents=True, exist_ok=True)
    summary = {}
    for s in filled:
        print(f"\n######## {s['patient_id']} ########")
        summary[s["patient_id"]] = {"sheet": s["path"], "direct": run_direct(s)}
        if "--loop" in sys.argv:
            summary[s["patient_id"]]["loop"] = run_loop(s, rounds)
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: {OUT / 'summary.json'}")
    print(f"AI 호출 {spent['calls']}번, 비용 약 ${spent['usd']:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
