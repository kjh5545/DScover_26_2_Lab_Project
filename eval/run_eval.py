"""임상시험 스크리닝 프롬프트 자동 평가.

웹 채팅으로 손으로 했던 사전 실험(시험 A–D, 재평가 세트 1·2)을 API로 반복 실행하고
정답과 비교해 일치율, 판정 흔들림, 탈락 후 질문 여부, 비용을 리포트로 남긴다.

사용 예:
    python run_eval.py --smoke                       # 케이스 1개 × 1회 (연결 확인용)
    python run_eval.py --models claude-opus-4-8 --repeats 3
    python run_eval.py --models claude-opus-4-8 claude-opus-5-5 claude-sonnet-5-5 claude-haiku-4-5 --repeats 3
"""

import argparse
import csv
import json
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import anthropic
from dotenv import load_dotenv

HERE = Path(__file__).parent
load_dotenv(HERE / ".env")

VERDICTS = ["통과", "탈락", "모름", "등록 후 확인"]
FINALS = ["적격", "부적격", "정보 부족"]

# 입력/출력 100만 토큰당 달러 (claude-api 스킬 기준, 2026-09)
PRICES = {
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0),
}

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "judgments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "verdict": {"type": "string", "enum": VERDICTS},
                    "evidence": {"type": "string"},
                },
                "required": ["id", "verdict", "evidence"],
                "additionalProperties": False,
            },
        },
        "final": {"type": "string", "enum": FINALS},
        "final_reason": {"type": "string"},
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "resolves": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["text", "resolves"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["judgments", "final", "final_reason", "questions"],
    "additionalProperties": False,
}

OUTPUT_INSTRUCTION = (
    "[출력 형식]\n"
    "지정된 JSON 형식으로만 답하세요. judgments에는 기준 ID마다 하나씩 판정과 근거를, "
    "final에는 적격 / 부적격 / 정보 부족 중 하나를, questions에는 확인 질문과 해결되는 기준 ID를 넣으세요. "
    "질문이 없으면 빈 배열로 두세요."
)


# 재평가 턴 전용. 1차 실행에서 Opus 4.8이 근거에는 "→ 통과"라고 쓰고 verdict에는 이전 판정(모름)을 넣은 혼동을 막는다
REEVAL_NOTE = "\nverdict에는 다시 판정한 결과(이후 판정)만 넣고, '이전 → 이후' 표시는 evidence에 쓰세요."


def model_params(model: str, effort: str) -> dict:
    """모델별 thinking/effort 설정. 웹에서 쓴 '추론 수준 높음'에 맞춘다."""
    fmt = {"type": "json_schema", "schema": OUTPUT_SCHEMA}
    if model.startswith("claude-haiku-4-5"):
        # Haiku 4.5는 effort를 지원하지 않고 thinking은 budget_tokens 방식
        return {
            "thinking": {"type": "enabled", "budget_tokens": 8000},
            "output_config": {"format": fmt},
        }
    if model.startswith("claude-opus-5-5"):
        # Opus 5.5는 thinking이 항상 켜져 있음. effort 기본값이 medium이라 명시
        return {"output_config": {"format": fmt, "effort": effort}}
    # Opus 4.8 / Sonnet 5.5: adaptive thinking을 명시적으로 켬
    return {
        "thinking": {"type": "adaptive"},
        "output_config": {"format": fmt, "effort": effort},
    }


def build_prompt(rules: str, patient: str, criteria: str) -> str:
    return f"{rules}\n\n{OUTPUT_INSTRUCTION}\n\n[환자]\n{patient}\n\n{criteria}"


def call(client, model, messages, effort):
    # thinking이 길어질 수 있어 max_tokens를 넉넉히 두고, HTTP 타임아웃을 피하려고 스트리밍으로 받는다
    with client.messages.stream(
        model=model,
        max_tokens=64000,
        messages=messages,
        **model_params(model, effort),
    ) as stream:
        resp = stream.get_final_message()
    if resp.stop_reason == "refusal":
        raise RuntimeError(f"refusal: {resp.stop_details}")
    if resp.stop_reason == "max_tokens":
        raise RuntimeError("max_tokens에 걸려 출력이 잘림")
    text = next(b.text for b in resp.content if b.type == "text")
    return resp, json.loads(text)


def run_one(client, model, case, rules, patient, effort, rep):
    """케이스 하나 실행. followup이 있으면 같은 대화에서 2턴째까지 진행하고 2턴 결과를 채점한다."""
    usage = Counter()
    messages = [{"role": "user", "content": build_prompt(rules, patient, case["criteria"])}]
    resp, out = call(client, model, messages, effort)
    usage["in"] += resp.usage.input_tokens
    usage["out"] += resp.usage.output_tokens
    turns = [out]
    if case.get("followup"):
        # thinking 블록을 포함한 응답을 그대로 이어 붙인다 (append-only)
        messages += [
            {"role": "assistant", "content": resp.content},
            {"role": "user", "content": case["followup"] + "\n\n" + OUTPUT_INSTRUCTION + REEVAL_NOTE},
        ]
        resp, out = call(client, model, messages, effort)
        usage["in"] += resp.usage.input_tokens
        usage["out"] += resp.usage.output_tokens
        turns.append(out)
    return {"case": case["id"], "model": model, "rep": rep, "turns": turns, "usage": dict(usage)}


def acceptable(expected):
    return expected if isinstance(expected, list) else [expected]


def score(case, out):
    got = {j["id"].strip(): j["verdict"] for j in out["judgments"]}
    rows = []
    for cid, exp in case["expected"].items():
        v = got.get(cid, "(누락)")
        rows.append({"criterion": cid, "expected": "/".join(acceptable(exp)), "got": v, "ok": v in acceptable(exp)})
    final_ok = out["final"] in case["expected_final"]
    q_ok = (len(out["questions"]) == 0) if case["expect_no_questions"] else True
    return rows, final_ok, q_ok


def cost(model, usage):
    pin, pout = PRICES.get(model, (0, 0))
    return usage["in"] / 1e6 * pin + usage["out"] / 1e6 * pout


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", default=["claude-opus-4-8"])
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--cases", nargs="*", help="실행할 케이스 ID (생략 시 전체)")
    ap.add_argument("--effort", default="high")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--smoke", action="store_true", help="A_basic 1회만 실행")
    ap.add_argument("--cases-file", default="cases.json", help="케이스 파일 (기본: S005 사전 실험 케이스)")
    ap.add_argument("--goldset", action="store_true", help="팀원 레이블 평가 세트(../goldset/goldset_v1.json) 사용")
    ap.add_argument("--rules", default="rules_prompt.md", help="규칙 프롬프트 파일 (기본: v2)")
    args = ap.parse_args()
    if args.goldset:
        args.cases_file = "../goldset/goldset_v1.json"

    data = json.loads((HERE / args.cases_file).read_text(encoding="utf-8"))
    rules = (HERE / args.rules).read_text(encoding="utf-8").strip()
    cases = data["cases"]
    if args.smoke:
        cases, args.repeats, args.models = [c for c in cases if c["id"] == "A_basic"], 1, args.models[:1]
    elif args.cases:
        cases = [c for c in cases if c["id"] in args.cases]

    client = anthropic.Anthropic()
    out_dir = HERE / "runs" / datetime.now().strftime("%Y%m%d_%H%M%S")
    (out_dir / "raw").mkdir(parents=True)

    jobs = [(m, c, r) for m in args.models for c in cases for r in range(1, args.repeats + 1)]
    print(f"실행: 모델 {len(args.models)}개 × 케이스 {len(cases)}개 × {args.repeats}회 = {len(jobs)}건")
    results, failures = [], []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        # 케이스에 patient가 있으면 그 환자, 없으면 파일 공통 환자(S005)를 쓴다
        futs = {ex.submit(run_one, client, m, c, rules, c.get("patient") or data.get("patient"), args.effort, r): (m, c["id"], r) for m, c, r in jobs}
        for f in as_completed(futs):
            m, cid, r = futs[f]
            try:
                res = f.result()
                results.append(res)
                (out_dir / "raw" / f"{m}__{cid}__{r}.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"  완료 {m} {cid} #{r}")
            except anthropic.AuthenticationError:
                sys.exit("API 키가 올바르지 않습니다. eval/.env의 ANTHROPIC_API_KEY를 확인하세요.")
            except anthropic.NotFoundError as e:
                failures.append((m, cid, r, f"모델을 찾을 수 없음: {e.message}"))
            except anthropic.BadRequestError as e:
                if "credit balance" in str(e.message).lower():
                    # 잔액 부족은 다시 보내도 같은 결과라 남은 작업을 모두 취소하고 멈춘다 (공용 키라 잔액이 갑자기 바닥날 수 있음)
                    for other in futs:
                        other.cancel()
                    sys.exit("API 크레딧 잔액이 부족해 중단했어요. 관리자에게 충전을 요청한 뒤 다시 실행하세요.")
                failures.append((m, cid, r, f"잘못된 요청: {e.message}"))
            except anthropic.RateLimitError:
                failures.append((m, cid, r, "요청 한도 초과 (SDK 재시도 후에도 실패)"))
            except anthropic.APIStatusError as e:
                failures.append((m, cid, r, f"API 오류 {e.status_code}: {e.message}"))
            except anthropic.APIConnectionError:
                failures.append((m, cid, r, "네트워크 오류"))
            except (RuntimeError, json.JSONDecodeError, StopIteration) as e:
                failures.append((m, cid, r, f"출력 처리 실패: {e}"))

    case_by_id = {c["id"]: c for c in cases}
    csv_rows, summary = [], defaultdict(lambda: Counter())
    spread = defaultdict(Counter)  # (model, case, criterion) -> 판정 분포
    total_cost = defaultdict(float)
    for res in sorted(results, key=lambda x: (x["model"], x["case"], x["rep"])):
        case = case_by_id[res["case"]]
        final_out = res["turns"][-1]
        rows, final_ok, q_ok = score(case, final_out)
        s = summary[(res["model"], res["case"])]
        s["runs"] += 1
        s["crit_ok"] += sum(r["ok"] for r in rows)
        s["crit_total"] += len(rows)
        s["final_ok"] += final_ok
        s["q_ok"] += q_ok
        s["questions"] += len(final_out["questions"])
        total_cost[res["model"]] += cost(res["model"], res["usage"])
        for r in rows:
            spread[(res["model"], res["case"], r["criterion"])][r["got"]] += 1
            csv_rows.append({"model": res["model"], "case": res["case"], "rep": res["rep"], **r})

    with open(out_dir / "results.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["model", "case", "rep", "criterion", "expected", "got", "ok"])
        w.writeheader()
        w.writerows(csv_rows)

    lines = [f"# 평가 결과 {out_dir.name}", "",
             f"- 모델: {', '.join(args.models)} · 규칙: {args.rules} · 케이스: {args.cases_file} · effort: {args.effort} · 반복: {args.repeats}회",
             f"- 소요 시간: {time.time() - t0:.0f}초 · 실패: {len(failures)}건", "",
             "## 케이스별 요약", "",
             "| 모델 | 케이스 | 실행 | 기준 일치율 | 최종 판단 일치 | 질문 규칙 지킴 | 평균 질문 수 |",
             "|---|---|---|---|---|---|---|"]
    for (m, cid), s in sorted(summary.items()):
        rate = s["crit_ok"] / s["crit_total"] * 100 if s["crit_total"] else 0
        q_rule = f'{s["q_ok"]}/{s["runs"]}' if case_by_id[cid]["expect_no_questions"] else "-"
        lines.append(f'| {m} | {cid} | {s["runs"]} | {rate:.0f}% | {s["final_ok"]}/{s["runs"]} | {q_rule} | {s["questions"] / s["runs"]:.1f} |')

    lines += ["", "## 모델별 합계", "", "| 모델 | 기준 일치율 | 최종 판단 일치 | 비용(USD) |", "|---|---|---|---|"]
    for m in args.models:
        ss = [s for (mm, _), s in summary.items() if mm == m]
        ok, tot = sum(s["crit_ok"] for s in ss), sum(s["crit_total"] for s in ss)
        fo, runs = sum(s["final_ok"] for s in ss), sum(s["runs"] for s in ss)
        lines.append(f'| {m} | {ok / tot * 100 if tot else 0:.0f}% ({ok}/{tot}) | {fo}/{runs} | ${total_cost[m]:.2f} |')

    lines += ["", "## 틀렸거나 흔들린 기준", "",
              "정답과 다른 판정이 한 번이라도 나온 기준, 또는 반복 실행에서 판정이 갈린 기준만 보여줍니다.", "",
              "| 모델 | 케이스 | 기준 | 정답 | 나온 판정 (횟수) |", "|---|---|---|---|---|"]
    for (m, cid, crit), cnt in sorted(spread.items()):
        exp = acceptable(case_by_id[cid]["expected"][crit])
        if len(cnt) > 1 or any(v not in exp for v in cnt):
            dist = ", ".join(f"{v} {n}" for v, n in cnt.most_common())
            lines.append(f"| {m} | {cid} | {crit} | {'/'.join(exp)} | {dist} |")

    if failures:
        lines += ["", "## 실패한 실행", ""] + [f"- {m} {cid} #{r}: {msg}" for m, cid, r, msg in failures]

    (out_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\n저장 위치: {out_dir}")


if __name__ == "__main__":
    main()
