"""평가 세트(goldset)로 handoff 형식 bundle을 만든다 (테스트·데모용, API 호출 없음).

1~4번을 새로 돌리지 않고, 평가 세트의 기준과 저장된 v3 판정으로 시작 상태를 만든다.
질문 루프(next_round → reassess)를 싸게 시험해 볼 때 쓴다.
"""

import json
from pathlib import Path

from src.agents.matcher import final_judgment

ROOT = Path(__file__).resolve().parent.parent.parent
GOLD = ROOT / "goldset" / "goldset_v1.json"
V3 = ROOT / "data" / "processed" / "goldset_cache_v3_claude-sonnet-5-5"


def make_bundle(patient_id: str) -> dict:
    """환자 ID → {"patient_id", "case_text", "profile", "trials": [{nct_id, criteria, judgments, final_judgment}]}"""
    gold = json.loads(GOLD.read_text(encoding="utf-8"))
    cases = [c for c in gold["cases"] if c["patient_id"] == patient_id]
    trials = []
    for c in cases:
        judgments = json.loads((V3 / f"match_{c['id']}.json").read_text(encoding="utf-8"))
        trials.append({"nct_id": c["trial"], "title": c["trial"],
                       "criteria": [{"id": r["id"], "type": r["kind"], "text": r["original"]} for r in c["rows"]],
                       "judgments": judgments, "final_judgment": final_judgment(judgments)})
    profile = json.loads((ROOT / "data" / "processed" / "eval_cache" / f"profile_{patient_id}.json")
                         .read_text(encoding="utf-8"))
    return {"patient_id": patient_id, "case_text": cases[0]["patient"], "profile": profile, "trials": trials}
