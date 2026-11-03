"""질문 생성 ablation 조건별 프롬프트를 만들고 검증한다 (API 호출 없음, 무료).

C_full은 src/question_builder.py의 실행판 상수에서 바이트 그대로 뽑고, A1·A2·A2s는 거기서 지정한 문장만 뺀다.
모든 치환은 원문에서 정확히 1번 나올 때만 적용한다 (원문이 바뀌면 실패).

실행:
  python experiments/question_ablation/build_prompts.py          # 프롬프트·diff·manifest 생성 후 검증
  python experiments/question_ablation/build_prompts.py --check  # 파일을 쓰지 않고 저장된 파일만 검증
결과: experiments/question_ablation/prompts/
"""

import argparse
import difflib
import hashlib
import json
import re
import subprocess
import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
OUT = HERE / "prompts"
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

SOURCE = "src/question_builder.py"
SOURCE_SYMBOL = "QUESTION_SYSTEM_PROMPT"
FILES = {"C0": "C0_baseline.txt", "C_full": "C_full_v233.txt", "A1": "A1_no_priority.txt",
         "A2": "A2_no_grouping.txt", "A2s": "A2s_no_grouping_commonality.txt"}

# 규칙 1의 우선순위 구성요소 (src/question_builder.py L45-52, L55-57)
A1_RULE1 = [
    "기록 검토가 필요하다는 이유만으로 직접 답변하는 질문보다 우선순위를 낮추지 마세요.\n",
    "다만 입력이나 기존 답변에서 해당 기록을 제공할 수 없다고 확인된 경우에는 그 사실을 고려하세요.\n",
    "질문 후보 안에서 다음 순서로 우선순위를 정하세요.\n",
    "① 판정 영향: 답변이나 제공된 기록이 선정 기준 미충족 또는 제외 기준 해당 여부를 판단하는 데 얼마나 직접적으로 도움이 되는지 고려합니다.\n",
    "② 공통성: 판정 영향이 비슷하면 여러 시험에 동시에 도움이 되는 질문을 우선합니다.\n",
    "③ 시험별 균형: 판정 영향과 공통성이 비슷하면 아직 질문이 덜 배정된 시험을 고려합니다.\n",
    "선정 기준과 제외 기준 사이에 일괄적인 우선순위를 두지 마세요.\n",
    "시험별 질문 수를 기계적으로 같게 맞추지 마세요.\n",
    "review.priority_notes에는 해당 질문이 어떤 판정 정보를 제공하는지 설명하세요.\n",
    "‘선정 기준이므로 먼저’, ‘기록 확인이 필요하므로 나중’처럼 분류나 확인 방식만을 근거로 순위를 설명하지 마세요.\n",
    "우선순위는 위 원칙에 따른 제안이며, 검증된 의학적 중요도 점수로 표현하지 마세요.\n",
]
# 규칙 1의 제거 내용을 가리켜 끊어진 참조가 되는 문장 (L63, L120)
A1_REFS = [
    "공통성이 높다는 이유만으로 규칙 1의 판정 영향보다 우선하지 마세요.\n",
    "다른 질문과 동일하게 규칙 1을 적용하세요.\n",
]
A1_SORT = "questions는 우선순위 순서로 정렬하세요.\n"
A1_TITLE = ("1. 질문 수와 우선순위\n", "1. 질문 수\n")

RULE2_START = "2. 공통 정보 묶기\n"
RULE3_START = "3. 한 질문에 한 주제\n"

A2S_COMMON = "② 공통성: 판정 영향이 비슷하면 여러 시험에 동시에 도움이 되는 질문을 우선합니다.\n"
A2S_BALANCE = ("③ 시험별 균형: 판정 영향과 공통성이 비슷하면 아직 질문이 덜 배정된 시험을 고려합니다.\n",
               "③ 시험별 균형: 판정 영향이 비슷하면 아직 질문이 덜 배정된 시험을 고려합니다.\n")

C0 = """당신은 임상시험 사전 스크리닝에서 환자에게 확인 질문을 만드는 담당자입니다.

입력은 환자 설명과 후보 임상시험들에서 ‘모름(unknown)’으로 판정된 기준입니다.
이 기준을 확인하기 위해 환자에게 물어볼 질문을 한국어로 만드세요.
질문은 [질문 수]의 최대 개수를 넘기지 마세요.

[출력 형식]
유효한 JSON 객체 하나만 출력하세요.
키와 문자열에는 직선 큰따옴표(")를 사용하세요.
코드 블록이나 JSON 밖의 설명은 쓰지 마세요.
trial에는 NCT ID를, criteria와 criterion_id에는 입력 기준 ID를 사용하세요.
다음 항목을 포함하세요.
1. questions
각 항목:
- question: 환자에게 보여 줄 질문.
- needed_info: 확인하려는 정보.
- resolves: 관련 시험과 기준 ID 목록.
2. not_asked
질문에 연결하지 않은 기준. 각 항목:
- trial
- criterion_id
- reason: ‘질문 수 제한으로 보류’ 또는 ‘검사·기록 또는 의료진의 추가 확인 필요’ 중 하나.
배열에 항목이 없으면 빈 배열로 출력하세요.
참고 구조:
{"questions": [{"question": "<질문>", "needed_info": "<필요한 정보>",
                "resolves": [{"trial": "<NCT ID>", "criteria": ["<기준 ID>"]}]}],
 "not_asked": [{"trial": "<NCT ID>", "criterion_id": "<기준 ID>", "reason": "<사유>"}]}"""

# C0에 들어가면 최적화 지시가 되는 표현. '검사·기록'은 not_asked 사유 값이라 검사에서 그 값만 제외한다
C0_FORBIDDEN = ["우선", "순서", "정렬", "묶", "공통", "영향", "균형", "원문", "기간", "단위", "용량", "보존", "가정", "추측",
                "한 주제", "두 문장", "간결", "쉬운", "이해", "민감", "진단", "결과지", "규칙", "적격", "유도", "답변", "모든"]
C0_REASONS = ["질문 수 제한으로 보류", "검사·기록 또는 의료진의 추가 확인 필요"]


def stub_missing_modules() -> None:
    """검증에는 네트워크가 필요 없으므로, 없는 패키지는 호출 불가 스텁으로 대체한다."""
    class Blocked:
        def __init__(self, *a, **k):
            raise RuntimeError("검증 중 API 호출 차단")
    for name in ("anthropic", "requests", "certifi"):
        try:
            __import__(name)
        except ImportError:
            mod = types.ModuleType(name)
            mod.Anthropic = Blocked
            sys.modules[name] = mod


def once(text: str, old: str, new: str = "") -> str:
    if text.count(old) != 1:
        raise SystemExit(f"정확히 1번 나와야 함 ({text.count(old)}번): {old!r}")
    return text.replace(old, new)


def make_a1(full: str) -> str:
    out = once(full, *A1_TITLE)
    for s in A1_RULE1 + A1_REFS + [A1_SORT]:
        out = once(out, s)
    return out


def make_a2(full: str) -> str:
    i, j = full.index(RULE2_START), full.index(RULE3_START)
    return full[:i] + full[j:]


def make_a2s(full: str) -> str:
    return once(once(make_a2(full), A2S_COMMON), *A2S_BALANCE)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def diff(a: str, b: str, name_a: str, name_b: str) -> str:
    return "\n".join(difflib.unified_diff(a.split("\n"), b.split("\n"), name_a, name_b, lineterm="", n=1)) + "\n"


def schema_of(prompt: str) -> dict:
    """프롬프트의 '참고 구조' JSON에서 키 구조를 뽑는다. 설명 문구 차이는 스키마 차이가 아니다."""
    obj = json.loads(prompt[prompt.index('{"questions"'):])
    def shape(x):
        if isinstance(x, dict):
            return {k: shape(v) for k, v in x.items()}
        if isinstance(x, list):
            return [shape(x[0])]
        return "str"
    return shape(obj)


def check(prompts: dict[str, str], full: str, review: str) -> list[str]:
    """검증 결과 줄 목록. 실패하면 예외."""
    from src.question_builder import question_input, write_questions, arrange, collect_materials
    import src.question_builder as qb
    from src.testing.goldset_bundle import make_bundle

    log = []
    def ok(cond, msg):
        if not cond:
            raise SystemExit(f"[실패] {msg}")
        log.append(f"PASS  {msg}")

    ok(prompts["C_full"].encode("utf-8") == full.encode("utf-8"), "C_full 바이트 == 실행판 상수")
    ok(sha(full) == "da845f66efbb1681" + sha(full)[16:], "실행판 해시가 STEP 1 기록과 일치")
    ok(full != review and "3. review\n" in review and "3. review\n" not in full, "C_full은 전문이 아니라 실행판")
    for k, p in prompts.items():
        ok("\r" not in p and not p.startswith("﻿"), f"{k}: CR·BOM 없음")

    # 변경 범위: 줄 단위로 빠진 줄·추가된 줄이 설계와 정확히 일치
    def changed(a, b):
        sm = list(difflib.ndiff(a.split("\n"), b.split("\n")))
        return ([l[2:] for l in sm if l.startswith("- ")], [l[2:] for l in sm if l.startswith("+ ")])
    rm, add = changed(full, prompts["A1"])
    want = [s.rstrip("\n") for s in A1_RULE1 + A1_REFS + [A1_SORT, A1_TITLE[0]]]
    ok(sorted(rm) == sorted(want) and add == [A1_TITLE[1].rstrip("\n")], f"A1 변경 범위: 제거 {len(rm)}줄, 제목 축약 1줄")
    rm, add = changed(full, prompts["A2"])
    block = full[full.index(RULE2_START):full.index(RULE3_START)].split("\n")[:-1]
    ok(rm == [l for l in block if True] or [l for l in rm if l] == [l for l in block if l], f"A2 변경 범위: 규칙 2 블록 {len(block)}줄만 제거")
    ok(not add, "A2 추가 줄 없음")
    rm, add = changed(prompts["A2"], prompts["A2s"])
    ok(sorted(rm) == sorted([A2S_COMMON.rstrip("\n"), A2S_BALANCE[0].rstrip("\n")]) and add == [A2S_BALANCE[1].rstrip("\n")],
       "A2s 변경 범위: A2에서 ② 제거 + ③ 문구 축약")

    # 스키마·예산
    base = schema_of(prompts["C_full"])
    for k, p in prompts.items():
        ok(schema_of(p) == base, f"{k}: JSON 키 구조가 C_full과 동일")
        ok("[질문 수]의 최대 개수를 넘기지 마세요." in p, f"{k}: 질문 예산 문장 유지")
        ok("질문 수 제한으로 보류" in p and "의료진의 추가 확인 필요" in p, f"{k}: not_asked 사유 값 유지")
        if k == "C0":
            ok("review" not in p, "C0: review 언급 없음")
        else:
            ok("review는 출력하지 마세요" in p, f"{k}: review 비출력 지시 유지")

    # 참조
    for k in ("C_full", "A1", "A2", "A2s"):
        nums = {int(n) for n in re.findall(r"\n\n(\d+)\. ", prompts[k][:prompts[k].index("[출력 형식]")])}
        refs = {int(n) for n in re.findall(r"규칙 (\d+)", prompts[k])}
        ok(refs <= nums, f"{k}: '규칙 n' 참조가 모두 존재하는 규칙을 가리킴 {sorted(refs)}")
    a1 = prompts["A1"]
    ok("규칙 1" not in a1, "A1: '규칙 1' 참조 없음")
    ok("판정 영향" not in a1 and "공통성" not in a1 and "시험별 균형" not in a1, "A1: 판정 영향·공통성·시험별 균형 없음")
    ok("공통성" not in prompts["A2s"] and "③ 시험별 균형: 판정 영향이 비슷하면" in prompts["A2s"], "A2s: 공통성 없음, ③은 판정 영향만 참조")
    ok("공통 정보 묶기" not in prompts["A2"] and "② 공통성" in prompts["A2"], "A2: 규칙 2 없음, 규칙 1의 ②는 유지")

    # C0
    c0 = prompts["C0"]
    probe = c0
    for r in C0_REASONS:
        probe = probe.replace(r, "")
    hits = [w for w in C0_FORBIDDEN if w in probe]
    ok(not hits, f"C0: 금지 표현 {len(C0_FORBIDDEN)}종 없음 {hits}")

    # 코드 경로: 조건 프롬프트가 그대로 LLM에 전달되고, 입력은 조건과 무관하게 같다
    seen = []
    real = qb.ask_json
    def fake(system, user, max_tokens=16000):
        seen.append((system, user))
        return {"questions": [], "not_asked": []}
    qb.ask_json = fake
    for pid in ("S004", "S008"):
        b = make_bundle(pid)
        mats = collect_materials(b)
        users = set()
        for k, p in prompts.items():
            seen.clear()
            write_questions(b, mats, 5, p)
            ok(seen[0][0] == p, f"{pid} {k}: 프롬프트가 바이트 그대로 전달됨")
            users.add(seen[0][1])
        ok(len(users) == 1, f"{pid}: 전 조건 사용자 메시지 동일 (sha {sha(users.pop())[:16]})")
    qb.ask_json = real
    return log


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="파일을 쓰지 않고 저장된 파일만 검증")
    args = ap.parse_args()
    stub_missing_modules()
    from src.question_builder import QUESTION_SYSTEM_PROMPT as FULL, QUESTION_SYSTEM_PROMPT_REVIEW as REVIEW

    built = {"C0": C0, "C_full": FULL, "A1": make_a1(FULL), "A2": make_a2(FULL), "A2s": make_a2s(FULL)}
    if args.check:
        prompts = {k: (OUT / f).read_bytes().decode("utf-8") for k, f in FILES.items()}
        for k in prompts:
            if prompts[k] != built[k]:
                raise SystemExit(f"[실패] {FILES[k]}가 원문에서 다시 만든 것과 다름")
    else:
        (OUT / "diffs").mkdir(parents=True, exist_ok=True)
        for k, f in FILES.items():
            (OUT / f).write_bytes(built[k].encode("utf-8"))
        for a, b in (("C_full", "A1"), ("C_full", "A2"), ("C_full", "A2s"), ("A2", "A2s"), ("C0", "C_full")):
            (OUT / "diffs" / f"{a}__{b}.diff").write_bytes(diff(built[a], built[b], FILES[a], FILES[b]).encode("utf-8"))
        manifest = {
            "source": {"path": SOURCE, "symbol": SOURCE_SYMBOL, "commit": git("rev-parse", "HEAD"),
                       "blob": git("rev-parse", f"HEAD:{SOURCE}"), "symbol_sha256": sha(FULL)},
            "encoding": "UTF-8, LF, no BOM, no trailing newline",
            "conditions": {k: {"file": FILES[k], "sha256": sha(built[k]), "bytes": len(built[k].encode("utf-8")),
                               "chars": len(built[k])} for k in FILES},
        }
        (OUT / "manifest.json").write_bytes((json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        prompts = built

    log = check(prompts, FULL, REVIEW)
    print("\n".join(log))
    print(f"\n검증 {len(log)}건 통과")
    for k, f in FILES.items():
        print(f"{k:7} {sha(prompts[k])}  {len(prompts[k]):>5}자  {f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
