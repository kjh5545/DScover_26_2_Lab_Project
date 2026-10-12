"""환자 10명(S001~S010) 각각에 대해 관련 질환의 모집 중 임상시험을 수집한다.

실행: python scripts/fetch_trials.py
결과: data/raw/trials/S001.json ~ S010.json

NOTE: 지금은 환자별 의심 질환을 사람이 매핑한 표(PATIENT_CONDITIONS)를 쓴다.
이후 환자 정보 추출 에이전트가 케이스 텍스트에서 질환을 직접 추론하도록 대체할 예정.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.tools.clinicaltrials_api import search_trials

# 각 환자 케이스에서 의심되는 대표 질환 (ClinicalTrials.gov 검색어)
PATIENT_CONDITIONS = {
    "S001": "acute pancreatitis",          # 만성 음주력 + 상복부 통증 + lipase/amylase 상승
    "S002": "hyperthyroidism",             # 두근거림 + 더위 못 참음 + 체중 감소 + 갑상선 비대 (Graves 의심)
    "S003": "nephrotic syndrome",          # 소아 + 눈 주위 부종 + 거품뇨 + 단백뇨
    "S004": "bladder cancer",              # 흡연력 + 무통성 혈뇨 + 방광 종괴
    "S005": "migraine with aura",          # 반복성 편측 박동성 두통 + 시각 전조
    "S006": "mucormycosis",                # 당뇨 조절 불량 + 안면 통증 + 비강 괴사 흑색 가피
    "S007": "pyloric stenosis",            # 영아 + 분출성 구토 + 올리브 모양 종괴
    "S008": "idiopathic pulmonary fibrosis",  # 진행성 호흡곤란 + 곤봉지 + 벌집 모양 폐 음영
    "S009": "infectious mononucleosis",    # 발열 + 인후통 + 후경부 림프절 + monospot 양성
    "S010": "retinal detachment",          # 커튼 치듯 갑작스런 시야 상실 + 광시증 + 비문증
}

MAX_TRIALS_PER_PATIENT = 20


def main() -> None:
    out_dir = ROOT / "data" / "raw" / "trials"
    out_dir.mkdir(parents=True, exist_ok=True)

    total = 0
    for patient_id, condition in PATIENT_CONDITIONS.items():
        trials = search_trials(condition, max_results=MAX_TRIALS_PER_PATIENT)
        out_path = out_dir / f"{patient_id}.json"
        out_path.write_text(
            json.dumps(
                {"patient_id": patient_id, "search_condition": condition, "trials": trials},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        total += len(trials)
        print(f"{patient_id} ({condition}): {len(trials)}건 저장 → {out_path.relative_to(ROOT)}")

    print(f"\n총 {total}건 수집 완료")


if __name__ == "__main__":
    main()
