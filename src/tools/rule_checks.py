"""코드로 확실히 판정할 수 있는 기준은 LLM 대신 코드가 판정한다 (1위 팀 ClarifyTrial에서 가져온 원칙).

지금 처리하는 것 (평가 세트 정답과 대조해 검증, scripts/check_rule_checks.py)
- 나이만 묻는 기준: "18 to 90 years of age", "Age ≥ 50", "under 16", "pediatric population" 등
- 임신·수유만 묻는 기준: 환자가 남성이거나 10세 미만이면 해당 없음 (통과)

함께 넣어 둔 계산 도구 (아직 파이프라인에는 연결 안 함, 상세 환자·재평가에서 쓸 예정)
- compare(): 수치 비교 (≥, <, 이상, 미만 등)
- convert(): 검사 단위 변환 (크레아티닌 mg/dL ↔ µmol/L 등)
- months_between(), within_window(): 날짜 계산 (휴약 기간, "최근 N개월 이내" 등)

원칙: 코드는 확실할 때만 판정한다. 나이 외의 조건이 섞인 기준은 건드리지 않고 LLM에 맡긴다.
"""

import re
from datetime import date

# ---------- 공통 ----------

def age_in_years(profile: dict) -> float | None:
    age = profile.get("age")
    if age is None:
        return None
    unit = (profile.get("age_unit") or "years").lower()
    if unit.startswith("month"):
        return age / 12
    if unit.startswith("week"):
        return age / 52.18
    if unit.startswith("day"):
        return age / 365.25
    return float(age)


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z]+", text.lower())


# ---------- 나이 기준 ----------

# 나이 표현을 지운 뒤 남아도 되는 단어 (이 밖의 단어가 남으면 "나이만 묻는 기준"이 아님)
_AGE_FILLER = set("""
age aged ages years year yrs old of the at time to and or inclusive between from subject subjects participant
participants patient patients male female males females both genders gender who are is be must entry into
screening upon visit population older younger than a an in""".split())

_NUM = r"(\d+(?:\.\d+)?)"
_UNIT = r"\s*(years?|yrs?|months?)?"


def _unit_factor(unit: str | None) -> float:
    return 1 / 12 if unit and unit.lower().startswith("month") else 1.0


def parse_age_criterion(text: str):
    """나이만 묻는 기준이면 (최소, 최소 포함 여부, 최대, 최대 포함 여부)를, 아니면 None을 돌려준다."""
    t = text.lower().replace("≥", ">=").replace("≤", "<=").replace("–", "-")
    lo = hi = None
    lo_incl = hi_incl = True
    m = (re.search(rf"(?:between|from)\s+{_NUM}{_UNIT}\s+(?:and|to)\s+{_NUM}{_UNIT}", t)
         or re.search(rf"{_NUM}{_UNIT}\s*(?:-|to)\s*{_NUM}{_UNIT}", t))
    if m:
        u = m.group(4) or m.group(2)
        lo, hi = float(m.group(1)) * _unit_factor(u), float(m.group(3)) * _unit_factor(u)
    else:
        m_op = re.search(rf"(>=|at least|>|over|older than)\s*{_NUM}{_UNIT}", t)
        m_older = re.search(rf"{_NUM}{_UNIT}\s*(?:of age\s*)?(?:and|or)\s*(?:older|over|above)", t)
        if m_op:
            op, n, u = m_op.group(1), m_op.group(2), m_op.group(3)
            lo, lo_incl = float(n) * _unit_factor(u), op in (">=", "at least")
        elif m_older:
            lo = float(m_older.group(1)) * _unit_factor(m_older.group(2))
        m2 = re.search(rf"(<=|under|below|less than|younger than|<)\s*{_NUM}{_UNIT}", t)
        if m2:
            op, n, u = m2.group(1), m2.group(2), m2.group(3)
            hi, hi_incl = float(n) * _unit_factor(u), op == "<="
        if lo is None and hi is None:
            if re.fullmatch(r"\s*(pediatric|paediatric) population\.?\s*", t):
                hi, hi_incl = 18.0, False
            else:
                return None
    # 나이 표현을 지우고 남은 단어가 군더더기뿐인지 확인
    rest = re.sub(r"\d+(?:\.\d+)?|>=|<=|[<>]|-", " ", t)
    for phrase in ("at least", "less than", "younger than", "older than", "under", "below", "over", "above",
                   "pediatric", "paediatric"):
        rest = rest.replace(phrase, " ")
    leftover = [w for w in _tokens(rest) if w not in _AGE_FILLER]
    if leftover:
        return None
    return lo, lo_incl, hi, hi_incl


def _in_range(age: float, rng) -> bool:
    lo, lo_incl, hi, hi_incl = rng
    if lo is not None and (age < lo or (age == lo and not lo_incl)):
        return False
    if hi is not None and (age > hi or (age == hi and not hi_incl)):
        return False
    return True


def _range_text(rng) -> str:
    lo, lo_incl, hi, hi_incl = rng
    parts = []
    if lo is not None:
        parts.append(f"{lo:g}세 {'이상' if lo_incl else '초과'}")
    if hi is not None:
        parts.append(f"{hi:g}세 {'이하' if hi_incl else '미만'}")
    return " ~ ".join(parts)


# ---------- 임신·수유 기준 ----------

_PREG_WORDS = set("""
pregnant pregnancy lactation lactating breastfeeding breast chest feeding nursing conceive childbearing child bearing
potential women woman female females participants participant patients patient subjects who are is with active
documented plans planning to or and of the if not could become assigned at birth eligible participate must agree take
rapid urine test before surgical procedure have negative result a an be""".split())
_PREG_CORE = re.compile(r"pregnan|lactat|breast|conceive|child-?bearing", re.I)


def is_pregnancy_only(text: str) -> bool:
    if not _PREG_CORE.search(text):
        return False
    return all(w in _PREG_WORDS for w in _tokens(text.replace("-", " ")))


# ---------- 기준별 코드 판정 ----------

def code_judgments(profile: dict, criteria: list[dict]) -> dict[str, dict]:
    """코드로 확실히 판정되는 기준만 {기준ID: 판정} 으로 돌려준다. criteria 항목: {"id", "type", "text"}"""
    out = {}
    age = age_in_years(profile)
    sex = (profile.get("sex") or "").upper()[:1]
    for c in criteria:
        cid, kind, text = c["id"], c.get("type", ""), c.get("text", "")
        exclusion = kind.startswith("excl") or cid.startswith("E")
        rng = parse_age_criterion(text) if age is not None else None
        if rng is not None:
            inside = _in_range(age, rng)
            # 선정 기준: 범위 안이면 통과 / 제외 기준: 범위 안이면(=제외 대상) 탈락
            verdict = ("fail" if inside else "pass") if exclusion else ("pass" if inside else "fail")
            out[cid] = {"criterion_id": cid, "verdict": verdict, "checked_by": "code",
                        "evidence": f"환자 나이 {age:g}세, 기준 {_range_text(rng)} → {'해당' if inside else '해당 안 함'} (코드 판정)",
                        "sub_condition_notes": []}
            continue
        if is_pregnancy_only(text) and (sex == "M" or (age is not None and age < 10)):
            who = "남성" if sex == "M" else f"{age:g}세 영유아"
            out[cid] = {"criterion_id": cid, "verdict": "pass", "checked_by": "code",
                        "evidence": f"환자가 {who}라 임신·수유 기준에 해당하지 않음 (코드 판정)",
                        "sub_condition_notes": []}
    return out


def apply_code_checks(llm_judgments: list[dict], code: dict[str, dict]) -> tuple[list[dict], list[dict]]:
    """LLM 판정 위에 코드 판정을 덮어쓴다. (합친 판정, 코드가 LLM과 다르게 바꾼 목록)"""
    merged, changed = [], []
    seen = set()
    for j in llm_judgments:
        cid = j.get("criterion_id")
        seen.add(cid)
        if cid in code:
            c = dict(code[cid], llm_verdict=j.get("verdict"))
            if j.get("verdict") != c["verdict"]:
                changed.append({"criterion_id": cid, "llm": j.get("verdict"), "code": c["verdict"]})
            merged.append(c)
        else:
            merged.append(j)
    for cid, c in code.items():   # LLM이 빠뜨린 기준도 코드로 채운다
        if cid not in seen:
            merged.append(dict(c, llm_verdict=None))
            changed.append({"criterion_id": cid, "llm": None, "code": c["verdict"]})
    return merged, changed


# ---------- 수치·날짜 계산 도구 ----------

_OPS = {">=": lambda a, b: a >= b, ">": lambda a, b: a > b, "<=": lambda a, b: a <= b, "<": lambda a, b: a < b,
        "이상": lambda a, b: a >= b, "초과": lambda a, b: a > b, "이하": lambda a, b: a <= b, "미만": lambda a, b: a < b}


def compare(value: float, op: str, threshold: float) -> bool:
    """compare(1.1, "<", 1.5) → True. op: >=, >, <=, <, 이상, 초과, 이하, 미만"""
    return _OPS[op](value, threshold)


# 검사 단위 변환 계수: (검사, 원래 단위, 바꿀 단위) → 곱할 값
_CONVERSIONS = {
    ("creatinine", "mg/dl", "umol/l"): 88.4, ("creatinine", "umol/l", "mg/dl"): 1 / 88.4,
    ("hemoglobin", "g/dl", "g/l"): 10.0, ("hemoglobin", "g/l", "g/dl"): 0.1,
    ("glucose", "mg/dl", "mmol/l"): 1 / 18.0, ("glucose", "mmol/l", "mg/dl"): 18.0,
}


def convert(test: str, value: float, unit_from: str, unit_to: str) -> float:
    """convert("creatinine", 1.1, "mg/dL", "µmol/L") → 97.24"""
    norm = lambda u: u.lower().replace("µ", "u").replace("μ", "u").replace(" ", "")
    f, t = norm(unit_from), norm(unit_to)
    if f == t:
        return value
    return value * _CONVERSIONS[(test.lower(), f, t)]


def months_between(earlier: date, later: date) -> float:
    """두 날짜 사이 개월 수 (평균 30.44일 기준). months_between(date(2025,4,15), date(2026,10,12)) → 약 17.9"""
    return (later - earlier).days / 30.44


def within_window(event: date, window_days: int, ref: date | None = None) -> bool:
    """event가 ref(기본 오늘) 기준 window_days일 이내인지. 예: 최근 14일 이내 혈액검사"""
    ref = ref or date.today()
    return 0 <= (ref - event).days <= window_days
