"""판정 프롬프트 아블레이션 (10/28 회의 계획 — 어떤 규칙이 어떤 오류를 고쳤나).

조건 (모델·입력 동일, 시스템 프롬프트만 교체 — prompts/ablation/*.txt):
  A 무규칙 / B AI 자작 규칙(대조군) / C v1 초기 / D v2 회의 결정 / E v3 현재 / F v3+규칙11·12

사용법:
  python scripts/eval_prompt_ablation.py --gen-control   # B 생성 (LLM 1회) — 최초 1번만
  python scripts/eval_prompt_ablation.py --smoke         # 케이스 1개 × 전 조건 × 1회 (동작 확인, ~$0.2)
  python scripts/eval_prompt_ablation.py --submit        # 본 실험: 전 조건 × 3회 × 15케이스, 배치 API 50% 할인
  python scripts/eval_prompt_ablation.py --report        # 저장된 결과로 지표·흔들림·오류 전이표 출력

주의: LLM 판정만 평가한다 (나이·임신 코드 검산 없이 — 프롬프트 효과를 분리하기 위함.
실제 파이프라인은 match_with_rules로 코드 검산이 덧붙는다).
반복 3회 해석: 3회 모두 틀리면 규칙 문제, 회차마다 다르면 원래 흔들리는 기준 (규칙 탓 아님).
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.llm import ask, ask_json, batch_ask_json, spent

PROMPT_DIR = ROOT / "prompts" / "ablation"
OUT_DIR = ROOT / "data" / "processed" / "ablation"
REPS = 3
EN = {"통과": "pass", "탈락": "fail", "모름": "unknown", "등록 후 확인": "post_enrollment"}

CONDITIONS = {  # 조건 코드 → 프롬프트 파일
    "A": "A_norules.txt", "B": "B_ai_rules.txt", "C": "C_v1.txt",
    "D": "D_v2.txt", "E": "E_v3.txt", "F": "F_v3_rules1112.txt",
}

GEN_CONTROL_PROMPT = """You are designing a system prompt for an LLM agent that
judges, criterion by criterion, whether a patient may be eligible for a
clinical trial. Inputs: the patient's short free-text description, a derived
profile, and parsed inclusion/exclusion criteria. For each criterion the agent
outputs one of: "pass", "fail", "unknown" (askable now), "post_enrollment"
(only exists after applying), plus quoted evidence.

Write the judgment RULES section yourself — whatever rules you believe produce
accurate, safe judgments. Do not ask questions. Output the COMPLETE system
prompt (role, verdict definitions, your rules, and the JSON output format:
a JSON array of {"criterion_id", "verdict", "evidence", "sub_condition_notes"}).
Output the prompt text only."""


def load_gold():
    gold = json.loads((ROOT / "goldset" / "goldset_v1.json").read_text(encoding="utf-8"))
    return gold["cases"]


def build_user(case: dict) -> str:
    """matcher.match(v3 입력 형식)와 동일한 사용자 입력 — 전 조건 공통 (실험 통제)."""
    profile = json.loads((ROOT / "data" / "processed" / "eval_cache" /
                          f"profile_{case['patient_id']}.json").read_text(encoding="utf-8"))
    criteria = [{"id": r["id"], "type": r["kind"], "text": r["original"]} for r in case["rows"]]
    return ("ORIGINAL PATIENT DESCRIPTION (authoritative):\n" + case["patient"]
            + "\n\nPATIENT PROFILE (derived; may include facts from the patient's answers):\n"
            + json.dumps(profile, ensure_ascii=False, indent=2)
            + "\n\nELIGIBILITY CRITERIA:\n" + json.dumps(criteria, ensure_ascii=False, indent=2))


def prompts() -> dict[str, str]:
    out = {}
    for code, fname in CONDITIONS.items():
        path = PROMPT_DIR / fname
        if path.exists():
            out[code] = path.read_text(encoding="utf-8")
    return out


def result_path(cond: str, rep: int, case_id: str) -> Path:
    return OUT_DIR / f"{cond}_rep{rep}" / f"{case_id}.json"


def save(path: Path, judgments) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(judgments, ensure_ascii=False, indent=2), encoding="utf-8")


def cmd_gen_control() -> None:
    text = ask("You design prompts for clinical NLP systems.", GEN_CONTROL_PROMPT)
    (PROMPT_DIR / "B_ai_rules.txt").write_text(text.strip() + "\n", encoding="utf-8")
    print(f"B 생성 완료 ({len(text)}자) → prompts/ablation/B_ai_rules.txt")
    print(f"비용: ${spent['usd']:.3f}")


def cmd_smoke() -> None:
    case = load_gold()[0]
    user = build_user(case)
    for cond, system in prompts().items():
        judgments = ask_json(system, user)
        n = len(judgments) if isinstance(judgments, list) else "형식 오류"
        print(f"조건 {cond}: 판정 {n}개 (기준 {len(case['rows'])}개)")
        save(result_path(cond, 0, case["id"]), judgments)
    print(f"\n스모크 OK — 비용: {spent['calls']}회 ${spent['usd']:.3f}")


def cmd_submit() -> None:
    cases = load_gold()
    ps = prompts()
    requests = {}
    for cond, system in ps.items():
        for rep in range(1, REPS + 1):
            for case in cases:
                if result_path(cond, rep, case["id"]).exists():
                    continue  # 이미 수집된 건 재요청 안 함 (중단 후 재개 가능)
                requests[f"{cond}|{rep}|{case['id']}"] = (system, build_user(case))
    if not requests:
        print("수집할 요청 없음 — 전부 완료됨. --report 실행하세요.")
        return
    print(f"배치 제출: 조건 {len(ps)}개 × {REPS}회 × {len(cases)}케이스 중 미완료 {len(requests)}건")
    results, cost = batch_ask_json(requests)
    ok = 0
    for cid, judgments in results.items():
        cond, rep, case_id = cid.split("|")
        if judgments is not None:
            save(result_path(cond, int(rep), case_id), judgments)
            ok += 1
    print(f"저장 {ok}/{len(requests)}건, 배치 비용 ${cost:.2f}")


def cmd_report() -> None:
    cases = load_gold()
    conds = sorted(prompts())
    # 지표: 전체 일치율 / 확정(통과·탈락) 정확도 / 3회 반복 흔들림
    print(f"{'조건':<4} {'전체 일치율 (3회)':<28} {'확정판정 정확도':<18} 일관 오류(3/3)  흔들림(1~2/3)")
    stable_errors: dict[str, set] = {}
    for cond in conds:
        rates, firm = [], []
        wrong_count: dict[tuple, int] = defaultdict(int)
        n_reps = 0
        for rep in range(1, REPS + 1):
            agree = total = firm_ok = firm_n = 0
            seen_rep = False
            for case in cases:
                path = result_path(cond, rep, case["id"])
                if not path.exists():
                    continue
                seen_rep = True
                by_id = {j.get("criterion_id"): j.get("verdict")
                         for j in json.loads(path.read_text(encoding="utf-8")) if isinstance(j, dict)}
                for cid, gold_ko in case["expected"].items():
                    gold_en = EN[gold_ko]
                    got = by_id.get(cid)  # 누락된 기준은 틀림으로 계산
                    total += 1
                    if got == gold_en:
                        agree += 1
                    else:
                        wrong_count[(case["id"], cid)] += 1
                    if got in ("pass", "fail"):
                        firm_n += 1
                        firm_ok += got == gold_en
            if seen_rep:
                n_reps += 1
                rates.append(agree / total if total else 0)
                firm.append(firm_ok / firm_n if firm_n else 0)
        if not rates:
            print(f"{cond:<4} (결과 없음)")
            continue
        consistent = {k for k, c in wrong_count.items() if c == n_reps and n_reps == REPS}
        unstable = {k for k, c in wrong_count.items() if 0 < c < n_reps}
        stable_errors[cond] = consistent
        rate_s = " / ".join(f"{r:.1%}" for r in rates)
        print(f"{cond:<4} {rate_s:<28} {sum(firm)/len(firm):<18.1%} {len(consistent):<14} {len(unstable)}")

    if "E" in stable_errors:
        print("\n== 오류 전이 (각 조건의 일관 오류 vs 최종 v3[E]) ==")
        for cond in conds:
            if cond == "E" or cond not in stable_errors:
                continue
            fixed = stable_errors[cond] - stable_errors["E"]
            broke = stable_errors["E"] - stable_errors[cond]
            print(f"{cond}→E: 고쳐짐 {len(fixed)}건 {sorted(fixed)[:5]}")
            print(f"      새로 깨짐 {len(broke)}건 {sorted(broke)[:5]}")

    out = OUT_DIR / "report.json"
    out.write_text(json.dumps({c: sorted(map(list, e)) for c, e in stable_errors.items()},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n일관 오류 목록 저장: {out.relative_to(ROOT)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gen-control", action="store_true")
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--submit", action="store_true")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()
    if args.gen_control:
        cmd_gen_control()
    elif args.smoke:
        cmd_smoke()
    elif args.submit:
        cmd_submit()
    elif args.report:
        cmd_report()
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
