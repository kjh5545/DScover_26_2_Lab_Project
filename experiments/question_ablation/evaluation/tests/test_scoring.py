"""채점 체계 로컬 검증 (API 호출 없음). 기대값은 synthetic_cases.json에 손으로 계산해 적었다.

실행: python experiments/question_ablation/evaluation/tests/test_scoring.py
"""

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
EVAL = HERE.parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(EVAL))

import scoring as sc  # noqa: E402

CASES = json.loads((EVAL / "examples" / "synthetic_cases.json").read_text(encoding="utf-8"))
REQUIRED = ["정상적인", "근거 없는", "기간·수치", "올바른 복수", "과잉 묶기", "일부 조건만", "resolves에", "기존 환자 정보"]


def scored_rows(rater="R-SYN"):
    """가상 사례 → 채점 완료된 질문·연결 행."""
    qrows, lrows = [], []
    for no, q in enumerate(CASES["questions"], 1):
        base = {"blind_id": "BSYN01", "patient_id": CASES["patient_id"], "question_no": no,
                "question_text": q["text"], "needed_info": q["needed_info"], "rater_id": rater}
        fail = "FAIL" in q["q"].values()
        qrows.append({**{c: "" for c in sc.QC}, **base, **q["q"], "n_links": len(q["links"]),
                      "n_trials": len({x["c"].split("|")[0] for x in q["links"]}),
                      "rationale": q.get("why", "") if fail else ""})
        for x in q["links"]:
            trial, cid = x["c"].split("|")
            need_why = x["coverage"] != "FULL" or x["preservation"] == "FAIL" or x["group_validity"] == "INVALID"
            lrows.append({**{k: "" for k in sc.LC}, **base, "trial_id": trial, "criterion_id": cid,
                          "criterion_type": CASES["criteria"][x["c"]]["type"],
                          "criterion_text": CASES["criteria"][x["c"]]["text"], "is_multi_link": int(len(q["links"]) > 1),
                          "preservation": x["preservation"], "coverage": x["coverage"],
                          "group_validity": x["group_validity"], "error_codes": x.get("error_codes", ""),
                          "rationale": q.get("why", "근거") if need_why else ""})
    return qrows, lrows


def annotation():
    return {tuple(k.split("|")): {**v, "candidate": True, "tier": ""} for k, v in CASES["annotation"].items()}


def clusters():
    return {k: {tuple(x.split("|")) for x in v} for k, v in CASES["clusters"].items()}


def fake_runs():
    qs = [{"text": q["text"], "needed_info": q["needed_info"],
           "resolves": [{"trial": x["c"].split("|")[0], "criteria": [x["c"].split("|")[1]]} for x in q["links"]]}
          for q in CASES["questions"]]
    return [{"run_key": f"{a}__SYN01__r{r}", "arm": a, "patient_id": "SYN01", "rep": r, "criteria": CASES["criteria"],
             "final_questions": qs} for a in ("C0", "C_full", "A1", "A2", "A2s") for r in (1, 2, 3)]


class Cases(unittest.TestCase):
    def test_all_required_cases_present(self):
        names = [q["case"] for q in CASES["questions"]]
        for want in REQUIRED:
            self.assertTrue(any(n.startswith(want) for n in names), want)
        self.assertIn("가상", CASES["notice"])

    def test_scored_sheet_passes_validation(self):
        self.assertEqual(sc.validate(*scored_rows()), [])

    def test_metrics_match_hand_calculation(self):
        got = sc.set_metrics(*scored_rows(), annotation(), clusters())
        for k, want in CASES["expected"].items():
            self.assertAlmostEqual(got[k], want, places=6, msg=k)

    def test_linked_is_not_covered(self):
        got = sc.set_metrics(*scored_rows(), annotation(), clusters())
        self.assertGreater(got["M3a"], got["M3b"])
        self.assertGreater(got["M3b"], got["M3c"])

    def test_unasked_condition_is_partial_not_distortion(self):
        _, links = scored_rows()
        r = next(x for x in links if x["criterion_id"] == "E3" and x["trial_id"] == "NCT00000001")
        self.assertEqual((r["preservation"], r["coverage"]), ("PASS", "PARTIAL"))

    def test_zero_denominator_is_none(self):
        q, l = scored_rows()
        got = sc.set_metrics([x for x in q if x["question_no"] == 1], [x for x in l if x["question_no"] == 1],
                             annotation(), clusters())
        for key in ("M5a", "M5b", "M6a"):
            self.assertIsNone(got[key], key)


class Validator(unittest.TestCase):
    def broken(self, sheet, idx, **change):
        q, l = scored_rows()
        (q if sheet == "q" else l)[idx].update(change)
        return sc.validate(q, l)

    def test_rejects_inconsistent_ratings(self):
        cases = [("l", 0, {"coverage": "NONE"}), ("l", 0, {"preservation": "FAIL"}), ("l", 0, {"coverage": "PARTIAL"}),
                 ("l", 0, {"group_validity": "VALID"}), ("l", 0, {"preservation": "NA"}), ("l", 0, {"error_codes": "Z9"}),
                 ("l", 0, {"preservation": "UNSURE"}), ("l", 0, {"rater_id": ""}), ("l", 0, {"coverage": "ALL"}),
                 ("q", 0, {"assumption": "FAIL"}), ("q", 0, {"overgroup": "PASS"}), ("q", 0, {"redundancy": "UNSURE"}),
                 ("q", 3, {"overgroup": "NA"}), ("q", 0, {"assumption_error": "A1"})]
        for sheet, idx, change in cases:
            self.assertTrue(self.broken(sheet, idx, **change), change)

    def test_unsure_with_reason_is_allowed(self):
        self.assertEqual(self.broken("l", 0, preservation="UNSURE", unsure_reason="원문 모호"), [])

    def test_r1_needs_target(self):
        self.assertTrue(self.broken("q", 1, redundancy="FAIL", redundancy_error="R1", rationale="중복"))
        self.assertEqual(self.broken("q", 1, redundancy="FAIL", redundancy_error="R1", rationale="중복", duplicate_of="1"), [])


class Blinding(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out, self.sealed = Path(self.tmp.name) / "rater", Path(self.tmp.name) / "sealed"
        self.map = sc.build_packet(fake_runs(), self.out, self.sealed, seed=11)

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_condition_information_in_packet(self):
        self.assertFalse((self.out / "blind_map.json").exists())
        for f in self.out.iterdir():
            text = f.read_text(encoding="utf-8-sig")
            for token in ("C_full", "A2s", "__r", '"arm"'):
                self.assertNotIn(token, text, f.name)
        for name in ("question_sheet.csv", "link_sheet.csv"):
            with open(self.out / name, encoding="utf-8-sig") as fh:
                header = next(csv.reader(fh))
            self.assertFalse(set(header) & set(sc.SCHEMA["forbidden_in_rater_packet"]), header)

    def test_order_does_not_reveal_condition(self):
        rows = sc.read_csv(self.out / "question_sheet.csv")
        ids = list(dict.fromkeys(r["blind_id"] for r in rows))
        self.assertEqual(ids, sorted(ids))
        arms = [self.map[b]["arm"] for b in ids]
        self.assertNotEqual(arms, sorted(arms))
        self.assertEqual(len(ids), 15)

    def test_question_order_kept_inside_set(self):
        rows = sc.read_csv(self.out / "question_sheet.csv")
        first = [r["question_no"] for r in rows if r["blind_id"] == rows[0]["blind_id"]]
        self.assertEqual(first, [str(i) for i in range(1, 9)])

    def test_unblind_requires_lock_and_unchanged_file(self):
        f = self.out / "question_sheet.csv"
        with self.assertRaises(PermissionError):
            sc.unblind(self.sealed, [f])
        sc.lock(self.sealed, [f])
        self.assertEqual(len(sc.unblind(self.sealed, [f])), 15)
        with open(f, "a", encoding="utf-8") as fh:
            fh.write("x")
        with self.assertRaises(PermissionError):
            sc.unblind(self.sealed, [f])

    def test_double_score_sample_covers_every_cell(self):
        picks = sc.double_score_sample(self.map, seed=3)
        self.assertEqual(len(picks), 5)
        self.assertEqual({self.map[b]["arm"] for b in picks}, {"C0", "C_full", "A1", "A2", "A2s"})


class Agreement(unittest.TestCase):
    def test_kappa_hand_value(self):
        r = sc.agreement(["P", "P", "F", "F"], ["P", "F", "F", "F"])
        self.assertAlmostEqual(r["percent"], 0.75)
        self.assertAlmostEqual(r["kappa"], 0.5)

    def test_kappa_undefined_when_constant(self):
        self.assertIsNone(sc.agreement(["P", "P"], ["P", "P"])["kappa"])

    def test_disagreements_go_to_adjudication_form(self):
        _, l1 = scored_rows("R1")
        _, l2 = scored_rows("R2")
        l2[0]["coverage"] = "PARTIAL"
        rows, stats = sc.disagreements("link", l1, l2, ["coverage", "preservation"],
                                       ("blind_id", "question_no", "trial_id", "criterion_id"))
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["rater1_value"], rows[0]["rater2_value"]), ("FULL", "PARTIAL"))
        self.assertEqual(set(rows[0]), set(sc.SCHEMA["adjudication_columns"]))
        self.assertEqual(stats["preservation"]["percent"], 1.0)


class Metrics(unittest.TestCase):
    def test_tier_rule(self):
        self.assertEqual(sc.impact_tier("2", "1"), "H")
        self.assertEqual(sc.impact_tier("1", "1"), "M")
        self.assertEqual(sc.impact_tier("0", "1"), "L")
        self.assertEqual(sc.impact_tier("UNSURE", "2"), "")

    def test_stability(self):
        self.assertAlmostEqual(sc.stability([[["a", "1"]], [["a", "1"]], [["a", "1"], ["a", "2"]]]), 2 / 3)
        self.assertIsNone(sc.stability([[], [], []]))

    def test_verdict_flip(self):
        k1, k2 = ("t", "1"), ("t", "2")
        self.assertEqual(sc.verdict_flip_rate([{k1: "pass", k2: "pass"}, {k1: "pass", k2: "unknown"}]), 0.5)

    def test_m8(self):
        t = lambda i: ("t", str(i))  # noqa: E731
        before = {t(1): "unknown", t(2): "unknown", t(3): "unknown", t(4): "pass", t(5): "unknown", t(6): "fail"}
        gold = {t(1): "pass", t(2): "fail", t(3): "unknown", t(4): "pass", t(5): "unknown", t(6): "fail"}
        after = {t(1): "pass", t(2): "unknown", t(3): "pass", t(4): "unknown", t(5): "post_enrollment", t(6): "pass"}
        m = sc.m8_metrics(before, after, gold)
        self.assertEqual((m["M8a"], m["M8b"], m["M8d"]), (0.5, 0.5, 1.0))
        self.assertEqual(m["to_post_enrollment"], 1)
        self.assertEqual(m["fail_to_pass"], [t(6)])

    def test_hangul_ratio(self):
        self.assertEqual(sc.hangul_ratio("혈뇨가 있나요"), 1.0)
        self.assertLess(sc.hangul_ratio("Do you have hematuria?"), sc.HANGUL_MIN)
        self.assertGreater(sc.hangul_ratio("특발성 폐섬유증(IPF)을 진단받으셨나요?"), sc.HANGUL_MIN)


class RealInputs(unittest.TestCase):
    """실제 저장소 데이터로 양식만 시험한다. 채점은 하지 않는다."""

    def test_preannotation_has_no_answer_information(self):
        sheets = sc.ROOT / "screening" / "detailed" / "인선"
        for pid, n_cand in (("S004", 13), ("S008", 23)):
            rows = sc.preannotation_rows(pid)
            self.assertEqual(sum(r["is_candidate"] for r in rows), n_cand)
            self.assertEqual(set(rows[0]), set(sc.PC))
            short = rows[0]["patient_text"]
            detail = next(sheets.glob(f"{pid}_detailed_sheet_filled.md")).read_text(encoding="utf-8")
            start = detail.index(short[:40], detail.index("## 상세 환자 설명"))
            added = detail[start + len(short):start + len(short) + 80].strip()
            self.assertGreater(len(added), 30)
            self.assertNotIn(added, json.dumps(rows, ensure_ascii=False))
            self.assertLess(len(short), 200)

    def test_packet_from_saved_real_questions(self):
        with tempfile.TemporaryDirectory() as d:
            runs = []
            for pid in ("S004", "S008"):
                path = sc.ROOT / "data" / "processed" / "detailed_eval" / "run_10-22_q-v2.3.3" / f"{pid}_loop.json"
                b = json.loads(path.read_text(encoding="utf-8"))
                crit = {f"{t['nct_id']}|{c['id']}": {"text": c["text"], "type": c.get("type", "")}
                        for t in b["trials"] for c in t["criteria"]}
                runs.append({"run_key": pid, "arm": "C_full", "patient_id": pid, "rep": 1, "criteria": crit,
                             "final_questions": b["rounds"][0]["questions"]})
            sc.build_packet(runs, Path(d) / "r", Path(d) / "s", seed=1)
            self.assertEqual(len(sc.read_csv(Path(d) / "r" / "question_sheet.csv")), 10)
            self.assertEqual(len(sc.read_csv(Path(d) / "r" / "link_sheet.csv")), 16)


class Documents(unittest.TestCase):
    def test_every_code_is_documented(self):
        text = (EVAL.parent / "04_error_taxonomy.md").read_text(encoding="utf-8")
        for code in list(sc.SCHEMA["error_codes"]) + sc.SCHEMA["values"]["simulator_code"]:
            self.assertIn(f"`{code}`", text, code)

    def test_every_metric_is_defined(self):
        text = (EVAL.parent / "04_question_rubric.md").read_text(encoding="utf-8")
        for m in ("M1a", "M1b", "M1c", "M2", "M3a", "M3b", "M3c", "M3d", "M4a", "M4b", "M4c", "M5a", "M5b", "M5c",
                  "M6a", "M6b", "M6c", "M7a", "M7b", "M8a", "M8b", "M8c", "M8d", "M8e", "D9"):
            self.assertIn(f"`{m}`", text, m)

    def test_rater_documents_do_not_reveal_conditions(self):
        for name in ("04_annotation_guideline.md", "04_error_taxonomy.md"):
            text = (EVAL.parent / name).read_text(encoding="utf-8")
            for token in ("C_full", "C0", "A2s", "A1_", "ablation", "규칙 2", "H1", "H2", "H3", "RQ"):
                self.assertNotIn(token, text, f"{name}: {token}")

    def test_templates_match_schema(self):
        with tempfile.TemporaryDirectory() as d:
            sc.write_templates(Path(d))
            for f in Path(d).iterdir():
                self.assertEqual(f.read_bytes(), (EVAL / "templates" / f.name).read_bytes(), f.name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
