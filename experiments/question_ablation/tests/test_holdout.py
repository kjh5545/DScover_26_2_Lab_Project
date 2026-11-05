"""확인 실험 입력 경로 검증. API를 부르지 않고, 실제 질문을 생성하지 않는다 (mock만 사용).

실패 메시지에도 환자 설명·판정값·근거를 넣지 않는다. 개수와 여부만 비교한다.
실행: python experiments/question_ablation/tests/test_holdout.py
"""

import copy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE.parent))

import holdout as ho  # noqa: E402
import run_pilot as rp  # noqa: E402

MAN = ho.manifest()


def json_key(d: dict, keys: tuple) -> str:
    import json
    return json.dumps({k: d[k] for k in keys}, ensure_ascii=False, sort_keys=True)
AVAILABLE = subprocess.run(["git", "cat-file", "-e", MAN["commit"]], cwd=rp.ROOT).returncode == 0


@unittest.skipUnless(AVAILABLE, "manifest 커밋 없음: git fetch origin 필요")
class Holdout(unittest.TestCase):
    def test_manifest_is_draft_not_frozen(self):
        self.assertTrue(MAN["status"].startswith("draft"))
        self.assertEqual(set(MAN["sheets"]), {"S002", "S010", "N001", "N002"})

    def test_blob_mismatch_is_rejected(self):
        bad = copy.deepcopy(MAN)
        bad["sheets"]["N001"]["blob"] = "0" * 40
        with self.assertRaisesRegex(ho.HoldoutError, "blob"):
            ho.sheet_text("N001", bad)

    def test_reading_does_not_touch_worktree(self):
        before = subprocess.run(["git", "status", "--porcelain"], cwd=rp.ROOT, capture_output=True, text=True).stdout
        for pid in MAN["sheets"]:
            ho.read_sheet(pid)
        after = subprocess.run(["git", "status", "--porcelain"], cwd=rp.ROOT, capture_output=True, text=True).stdout
        self.assertEqual(before, after)

    def test_inputs_match_sheets(self):
        for pid in MAN["sheets"]:
            r = ho.input_check(pid)
            self.assertTrue(r["ids_match_sheet"] and r["initial_judgment_all"], pid)
            self.assertEqual(r["sheet_parse_problems"], 0, pid)

    def test_new_patients_load_from_handoff(self):
        for pid in ("N001", "N002"):
            with self.assertRaises(Exception):
                rp.make_bundle(pid)          # 평가 세트 전용 경로는 실패한다
            b = ho.load_bundle(pid)
            self.assertTrue(b["trials"])
            self.assertEqual({k for t in b["trials"] for c in t["criteria"] for k in c}, set(ho.GOLDSET_KEYS))

    def test_shape_changes_question_input_only_for_handoff_patients(self):
        mats = lambda b: rp.qb.question_input(b, rp.qb.collect_materials(b), rp.MAX_QUESTIONS)  # noqa: E731
        n = [mats(ho.load_bundle("N001", s)) for s in ("goldset", "service")]
        self.assertNotEqual(*n)
        s = [mats(ho.load_bundle("S002", s)) for s in ("goldset", "service")]
        self.assertEqual(*s)

    def test_goldset_shape_matches_pilot_loader_for_s_patients(self):
        self.assertEqual(ho.load_bundle("S010")["trials"], rp.make_bundle("S010")["trials"])

    def test_pilot_format_is_identical_across_cohorts(self):
        """파일럿 형식에서는 여섯 환자의 질문 생성 입력 형식 요소가 같다 (제목·필요 정보 없음, 같은 머리글)."""
        forms = [ho.input_format(p) for p in ho.PILOT + ho.CONFIRM]
        keys = ("headers", "trial_title_in_input", "needed_info_in_input", "criteria_keys")
        self.assertEqual(len({json_key(f, keys) for f in forms}), 1)
        self.assertFalse(forms[0]["trial_title_in_input"] or forms[0]["needed_info_in_input"])
        self.assertTrue(all(f["final_judgment_recomputed_same"] for f in forms))
        svc = ho.input_format("N001", "service")
        self.assertTrue(svc["trial_title_in_input"] and svc["needed_info_in_input"])

    def test_no_detailed_or_gold_text_in_inputs(self):
        for pid in ho.PILOT + ho.CONFIRM:
            r = ho.leak_check(pid)
            self.assertTrue(r["case_text_equals_sheet_short"], pid)
            self.assertGreater(r["detailed_fragments_checked"] + r["gold_evidence_checked"], 0, pid)
            for shape in ("goldset", "service"):
                self.assertEqual(r["found"][shape], {"detailed_fragments": 0, "gold_evidence": 0}, pid)

    def test_initial_judgment_provenance(self):
        for pid in ho.PILOT + ho.CONFIRM:
            p = ho.provenance(pid)
            self.assertEqual((p["judge_prompt"], p["code_changed_verdict"], p["validator_fixed"]), ("v3", 0, 0), pid)
            self.assertIn("claude-sonnet-5-5", p["model"])

    def test_confirm_cohort_is_separate_and_unpaid(self):
        pilot_versions = rp.compute_versions()
        with ho.use_cohort("confirm"):
            self.assertEqual(rp.PATIENTS, ho.CONFIRM)
            v = rp.compute_versions()
            self.assertEqual(set(v["input_sha256"]), set(ho.CONFIRM))
            self.assertIn("experiments/question_ablation/holdout_manifest.json", v["file_blobs"])
            self.assertFalse(any(f.startswith("screening/") for f in v["file_blobs"]))
            self.assertEqual(set(rp.denominators()), set(ho.CONFIRM))
            with self.assertRaisesRegex(rp.GateError, "확인 실험"):
                rp.paid_gate(None)
            self.assertIn("preannotation_confirm", str(rp.ANNOTATION_RECORD))
        self.assertEqual(rp.PATIENTS, ("S004", "S008"))
        self.assertEqual(rp.compute_versions(), pilot_versions)
        rp.verify_versions()                       # 파일럿 잠금은 그대로 통과

    def test_mock_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            one = {**MAN, "sheets": {"N002": MAN["sheets"]["N002"]}}
            r = ho.mock_dry_run(Path(tmp) / "m", one)["N002"]
            self.assertEqual(r["questions"], {"ok": 5})
            self.assertEqual(r["downstream"], {"ok": 4})
            self.assertTrue(r["question_inputs_identical_across_arms"])
            files = list((Path(tmp) / "m" / "attempts").glob("*.json"))
            self.assertTrue(files and all('"model": "mock"' in f.read_text(encoding="utf-8") for f in files))


if __name__ == "__main__":
    unittest.main(verbosity=2)
