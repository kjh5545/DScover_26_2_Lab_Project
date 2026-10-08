"""두 프롬프트 버전의 실행 결과를 현재 cases.json 정답으로 다시 채점해 나란히 비교한다.

사용 예:
    python compare.py --a runs/20261003_151826 runs/<재실행1> runs/<재실행2> --b runs/<v3 실행> --out 비교_v2_v3.md

--a / --b에 폴더를 여러 개 주면 뒤에 오는 폴더의 (모델, 케이스) 결과가 앞의 것을 대체한다.
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path

from run_eval import HERE, acceptable, score


def load(dirs):
    picked = {}
    for d in dirs:
        by_pair = defaultdict(list)
        for f in sorted((Path(d) / "raw").glob("*.json")):
            res = json.loads(f.read_text(encoding="utf-8"))
            by_pair[(res["model"], res["case"])].append(res)
        picked.update(by_pair)  # 뒤 폴더가 앞 폴더를 대체
    return picked


def metrics(runs, case):
    m = defaultdict(int)
    wrong = defaultdict(lambda: defaultdict(int))
    for res in runs:
        out = res["turns"][-1]
        rows, final_ok, q_ok = score(case, out)
        m["runs"] += 1
        m["ok"] += sum(r["ok"] for r in rows)
        m["tot"] += len(rows)
        m["final"] += final_ok
        m["q"] += q_ok
        for r in rows:
            if not r["ok"]:
                wrong[r["criterion"]][r["got"]] += 1
    return m, wrong


def cell(m, case):
    if not m["runs"]:
        return "-", "-", "-"
    crit = f'{m["ok"] / m["tot"] * 100:.0f}%'
    final = f'{m["final"]}/{m["runs"]}'
    q = f'{m["q"]}/{m["runs"]}' if case["expect_no_questions"] else "-"
    return crit, final, q


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", nargs="+", required=True, help="기준 버전 실행 폴더들")
    ap.add_argument("--b", nargs="+", required=True, help="비교 버전 실행 폴더들")
    ap.add_argument("--la", default="v2")
    ap.add_argument("--lb", default="v3")
    ap.add_argument("--out", default="비교.md")
    ap.add_argument("--cases-file", default="cases.json")
    ap.add_argument("--goldset", action="store_true", help="팀원 레이블 평가 세트(../goldset/goldset_v1.json) 사용")
    args = ap.parse_args()
    if args.goldset:
        args.cases_file = "../goldset/goldset_v1.json"

    cases = {c["id"]: c for c in json.loads((HERE / args.cases_file).read_text(encoding="utf-8"))["cases"]}
    A, B = load(args.a), load(args.b)
    models = sorted({m for m, _ in A} | {m for m, _ in B})
    la, lb = args.la, args.lb

    lines = [f"# {la} vs {lb} 비교", "",
             "칸 안의 값: 기준 일치율 · 최종 판단 일치 · 탈락 후 질문 안 하기 (해당 케이스만)", "",
             f"| 모델 | 케이스 | {la} 기준 | {lb} 기준 | {la} 최종 | {lb} 최종 | {la} 질문 규칙 | {lb} 질문 규칙 |",
             "|---|---|---|---|---|---|---|---|"]
    totals = {la: defaultdict(lambda: defaultdict(int)), lb: defaultdict(lambda: defaultdict(int))}
    wrong_lines = []
    for m in models:
        for cid, case in cases.items():
            ma, wa = metrics(A.get((m, cid), []), case)
            mb, wb = metrics(B.get((m, cid), []), case)
            for lab, mm in ((la, ma), (lb, mb)):
                for k in ("ok", "tot", "final", "runs"):
                    totals[lab][m][k] += mm[k]
            ca, cb = cell(ma, case), cell(mb, case)
            lines.append(f"| {m} | {cid} | {ca[0]} | {cb[0]} | {ca[1]} | {cb[1]} | {ca[2]} | {cb[2]} |")
            for lab, w in ((la, wa), (lb, wb)):
                for crit, dist in w.items():
                    exp = "/".join(acceptable(case["expected"][crit]))
                    d = ", ".join(f"{v} {n}" for v, n in dist.items())
                    wrong_lines.append(f"| {lab} | {m} | {cid} | {crit} | {exp} | {d} |")

    lines += ["", "## 모델별 합계", "", f"| 모델 | {la} 기준 일치율 | {lb} 기준 일치율 | {la} 최종 일치 | {lb} 최종 일치 |", "|---|---|---|---|---|"]
    for m in models:
        ta, tb = totals[la][m], totals[lb][m]
        pa = f'{ta["ok"] / ta["tot"] * 100:.0f}%' if ta["tot"] else "-"
        pb = f'{tb["ok"] / tb["tot"] * 100:.0f}%' if tb["tot"] else "-"
        lines.append(f'| {m} | {pa} | {pb} | {ta["final"]}/{ta["runs"]} | {tb["final"]}/{tb["runs"]} |')

    lines += ["", "## 정답과 다른 판정", "", "| 버전 | 모델 | 케이스 | 기준 | 정답 | 나온 판정 (횟수) |", "|---|---|---|---|---|---|"] + sorted(wrong_lines)
    (HERE / args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
