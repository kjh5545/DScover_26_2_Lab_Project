"""사전 주석 보조 스크립트 검증 (API 호출 없음). 주석 값은 테스트 안에서만 쓰는 가짜 값이다.

실행: python experiments/question_ablation/evaluation/tests/test_annotation_tools.py
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
EVAL = HERE.parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(EVAL))

import annotation_tools as at  # noqa: E402
import scoring as sc  # noqa: E402

PID = "S004"
CORE2 = {"centrality": "2", "centrality_evidence": "원문: 테스트", "core_part": sc.WHOLE, "core_info": "테스트 정보"}
NOT2 = {"centrality": "1", "core_part": "", "core_info": ""}


def filled(rater: str, change: dict | None = None) -> list[dict]:
    """원본 주석표의 후보 행에 가짜 값을 채운다. 앞의 3개는 핵심성 2점(핵심 부분 '전체'). change: {후보 순번: {열: 값}}."""
    rows = sc.read_csv(EVAL / "preannotation" / f"{PID}_preannotation.csv")
    i = 0
    for r in rows:
        if r["is_candidate"] != "1":
            continue
        r.update(askable="ASK_PATIENT", centrality="0", rationale="테스트 근거", rater_id=rater)
        if i < 3:
            r.update(CORE2)
        r.update((change or {}).get(i, {}))
        i += 1
    return rows


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def save(self, name: str, rows: list[dict], cols=None) -> Path:
        path = self.root / name
        sc.write_csv(path, cols or sc.PC, rows)
        return path

    def adjudicate(self, adj_path: Path, value) -> None:
        adj = sc.read_csv(adj_path)
        for x in adj:
            x.update(final_value=value(x), reason="토의 결과", adjudicator_id="J1")
        sc.write_csv(adj_path, sc.SCHEMA["adjudication_columns"], adj)


class Check(Base):
    def test_blank_template_fails_and_filled_passes(self):
        self.assertTrue(at.check(PID, sc.read_csv(EVAL / "preannotation" / f"{PID}_preannotation.csv")))
        self.assertEqual(at.check(PID, filled("A1")), [])

    def test_no_decisiveness_column(self):
        """M7-B: 직접성은 더 이상 주석하지 않는다."""
        self.assertNotIn("decisiveness", sc.PC)
        self.assertNotIn("decisiveness", sc.SCHEMA["values"])

    def test_rules(self):
        cases = (({0: {"askable": "maybe"}}, "askable 값"),
                 ({3: {"centrality": "UNSURE"}}, "판단 불가 사유"),
                 ({0: {"rationale": ""}}, "rationale"),
                 ({0: {"criterion_text": "바꾼 문구"}}, "주어진 열"),
                 ({0: {"centrality_evidence": ""}}, "근거"),
                 ({0: {"core_part": ""}}, "2점에는 core_part"),     # 표시 누락은 '전체'와 구분된다
                 ({0: {"core_info": ""}}, "2점에는 core_part"),
                 ({3: {"core_part": "x", "core_info": "y"}}, "2점 기준에만"))
        for change, msg in cases:
            self.assertTrue(any(msg in e for e in at.check(PID, filled("A1", change))), msg)
        self.assertEqual(at.check(PID, filled("A1", {0: {"core_part": "질환 확진"}})), [])
        cited = filled("A1", {0: {"centrality_evidence": "EV01"}})
        self.assertTrue(any("근거 목록" in e for e in at.check(PID, cited, set())))
        self.assertEqual(at.check(PID, cited, {"EV01"}), [])
        rows = filled("A1")
        next(r for r in rows if r["is_candidate"] == "0")["askable"] = "ASK_PATIENT"
        self.assertTrue(any("후보가 아닌" in e for e in at.check(PID, rows)))
        self.assertTrue(any("원본과 다름" in e for e in at.check(PID, rows[:-1])))

    def test_clusters(self):
        cand = [r for r in filled("A1") if r["is_candidate"] == "1"]
        row = lambda cid, r: {"cluster_id": cid, "patient_id": PID, "shared_fact": "흡연력",  # noqa: E731
                              "trial_id": r["trial_id"], "criterion_id": r["criterion_id"], "rationale": "x", "rater_id": "A1"}
        self.assertEqual(at.check_clusters(PID, [row("K1", cand[0]), row("K1", cand[1])]), [])
        self.assertTrue(at.check_clusters(PID, [row("K1", cand[0])]))
        self.assertTrue(at.check_clusters(PID, [row("K1", cand[0]), row("K2", cand[0]), row("K2", cand[1])]))
        non = next(r for r in filled("A1") if r["is_candidate"] == "0")
        self.assertTrue(at.check_clusters(PID, [row("K1", cand[0]), row("K1", non)]))


class Evidence(Base):
    def test_evidence_list(self):
        cols = sc.SCHEMA["safety_evidence_columns"]
        fixed = {c: "x" for c in cols} | {"evidence_id": "EV01", "review_status": "고정"}
        pending = dict(fixed, evidence_id="EV02", review_status="작성·검토 대기", reason_for_2="", reviewed_by="",
                       fixed_date="")
        self.assertEqual(at.check_evidence_list(self.save("e.csv", [fixed, pending], cols)), [])
        self.assertEqual(at.evidence_ids(self.root / "e.csv"), {"EV01"})      # 검토 대기 행은 인용할 수 없다
        bad = [fixed, dict(fixed, source=""), dict(fixed, evidence_id="X1"), dict(fixed, evidence_id="EV03",
                                                                                   review_status="완료")]
        errs = at.check_evidence_list(self.save("b.csv", bad, cols))
        for msg in ("빈 열", "EV로", "중복", "review_status"):
            self.assertTrue(any(msg in e for e in errs), msg)
        self.assertEqual(at.evidence_ids(self.root / "b.csv"), {"EV01"})
        self.assertIsNone(at.evidence_ids(self.root / "none.csv"))


class CompareAndFinalize(Base):
    def pair(self):
        a = self.save("a.csv", filled("A1"))
        b = self.save("b.csv", filled("A2", {0: NOT2, 4: {"askable": "UNSURE", "unsure_reason": "모름"}, 5: CORE2}))
        return a, b

    def test_compare_counts_and_template(self):
        a, b = self.pair()
        r = at.compare(PID, a, b, self.root / "out")
        self.assertEqual(r["candidates"], 13)
        self.assertEqual((r["H"]["rater1"], r["H"]["rater2"], r["H"]["both"], r["H"]["either_h_any"]), (3, 3, 2, 4))
        self.assertEqual(r["core_part"], {"whole_rater1": 3, "whole_rater2": 3, "same_text_when_both_H": 2, "both_H": 2})
        self.assertEqual(r["to_adjudicate"], 8)
        self.assertAlmostEqual(r["agreement"]["askable"]["percent"], 12 / 13)
        adj = sc.read_csv(self.root / "out" / f"{PID}_adjudication.csv")
        self.assertEqual({x["field"] for x in adj}, {"askable", "centrality", "centrality_evidence", "core_part", "core_info"})
        self.assertTrue(all(x["final_value"] == "" for x in adj))
        with self.assertRaises(FileExistsError):
            at.compare(PID, a, b, self.root / "out")

    def test_both_unsure_askable_needs_adjudication(self):
        same = {3: {"askable": "UNSURE", "unsure_reason": "모름"}}
        a, b = self.save("a.csv", filled("A1", same)), self.save("b.csv", filled("A2", same))
        self.assertEqual(at.compare(PID, a, b, self.root / "out")["to_adjudicate"], 1)

    def test_same_rater_id_rejected(self):
        a, b = self.save("a.csv", filled("A1")), self.save("b.csv", filled("A1"))
        with self.assertRaisesRegex(ValueError, "rater_id"):
            at.compare(PID, a, b, self.root / "out")

    def test_finalize_requires_complete_adjudication(self):
        a, b = self.pair()
        at.compare(PID, a, b, self.root / "out")
        adj_path = self.root / "out" / f"{PID}_adjudication.csv"
        with self.assertRaisesRegex(ValueError, "조정 오류"):
            at.finalize(PID, a, b, adj_path, self.root / "final")
        self.adjudicate(adj_path, lambda x: "ASK_RECORD" if x["field"] == "askable" else x["rater1_value"])
        s = at.finalize(PID, a, b, adj_path, self.root / "final")
        self.assertEqual((s["rows"], s["h_strict"], s["h_any"], s["core_part_whole"]), (13, 3, 4, 3))
        rows = sc.read_csv(self.root / "final" / f"{PID}_final.csv")
        self.assertEqual(list(rows[0]), sc.SCHEMA["preannotation_final_columns"])
        self.assertNotIn("final_decisiveness", rows[0])
        self.assertEqual(sum(r["final_askable"] == "ASK_RECORD" for r in rows), 1)
        self.assertTrue(any("토의 결과" in r["adjudication_note"] for r in rows))
        with self.assertRaises(FileExistsError):
            at.finalize(PID, a, b, adj_path, self.root / "final")

    def test_finalize_rejects_unsure_askable_and_stale_table(self):
        a, b = self.pair()
        at.compare(PID, a, b, self.root / "out")
        adj_path = self.root / "out" / f"{PID}_adjudication.csv"
        self.adjudicate(adj_path, lambda x: x["rater2_value"])
        with self.assertRaisesRegex(ValueError, "UNSURE"):
            at.finalize(PID, a, b, adj_path, self.root / "final")
        sc.write_csv(adj_path, sc.SCHEMA["adjudication_columns"], sc.read_csv(adj_path)[:-1])
        with self.assertRaisesRegex(ValueError, "현재 불일치와 다름"):
            at.finalize(PID, a, b, adj_path, self.root / "final")

    def test_core_part_adjudicated_and_carried(self):
        a = self.save("a.csv", filled("A1", {0: {"core_part": "질환 확진", "core_info": "병리 결과"}}))
        b = self.save("b.csv", filled("A2", {0: {"core_part": "질환 확진 및 병기", "core_info": "병리 결과"}, 1: NOT2}))
        r = at.compare(PID, a, b, self.root / "out")
        adj_path = self.root / "out" / f"{PID}_adjudication.csv"
        self.assertEqual(sorted(x["field"] for x in sc.read_csv(adj_path)),
                         ["centrality", "core_info", "core_part", "core_part"])
        self.assertEqual((r["core_part"]["whole_rater1"], r["core_part"]["whole_rater2"]), (2, 1))
        self.adjudicate(adj_path, lambda x: {"core_part": "질환 확진", "centrality": "1"}.get(x["field"], ""))
        s = at.finalize(PID, a, b, adj_path, self.root / "f")
        rows = sc.read_csv(Path(s["file"]))
        self.assertEqual(sorted(x["final_core_part"] for x in rows if x["final_core_part"]), ["전체", "질환 확진"])
        self.assertEqual((s["h_strict"], s["core_part_whole"], s["core_part_specific"]), (2, 1, 1))
        self.assertTrue(all((x["h_strict"] == "true") == (x["final_centrality"] == "2") for x in rows))

    def test_core_fields_cleared_when_final_centrality_not_2(self):
        a = self.save("a.csv", filled("A1", {0: {"core_part": "x", "core_info": "y"}}))
        b = self.save("b.csv", filled("A2", {0: NOT2}))
        at.compare(PID, a, b, self.root / "out")
        adj_path = self.root / "out" / f"{PID}_adjudication.csv"
        self.adjudicate(adj_path, lambda x: "1" if x["field"] == "centrality" else "")
        rows = sc.read_csv(Path(at.finalize(PID, a, b, adj_path, self.root / "f")["file"]))
        self.assertFalse(any(x["final_core_part"] or x["final_core_info"] for x in rows if x["final_centrality"] != "2"))

    def test_zero_h_is_allowed_with_note(self):
        """M5-B: H가 0개여도 확정표를 만들고, M4a가 값 없음이 된다는 안내를 남긴다."""
        none = {i: NOT2 for i in range(3)}
        a, b = self.save("a.csv", filled("A1", none)), self.save("b.csv", filled("A2", none))
        at.compare(PID, a, b, self.root / "out")
        s = at.finalize(PID, a, b, self.root / "out" / f"{PID}_adjudication.csv", self.root / "f")
        self.assertEqual(s["h_strict"], 0)
        self.assertIn("값 없음", s["note"])

    def test_final_file_passes_runner_population_check(self):
        """확정표가 실행기의 잠금 검사와 같은 모집단·형식인지 (S004 후보 13개)."""
        a, b = self.save("a.csv", filled("A1")), self.save("b.csv", filled("A2"))
        at.compare(PID, a, b, self.root / "out")
        s = at.finalize(PID, a, b, self.root / "out" / f"{PID}_adjudication.csv", self.root / "f")
        cand = {(r["trial_id"], r["criterion_id"]) for r in at.source_rows(PID).values() if r["is_candidate"] == "1"}
        rows = sc.read_csv(Path(s["file"]))
        self.assertEqual({(r["trial_id"], r["criterion_id"]) for r in rows}, cand)
        self.assertTrue(all(r["final_askable"] in sc.SCHEMA["values"]["askable"][:3] for r in rows))
        self.assertEqual(json.loads(json.dumps(s))["h_strict"], 3)


class FinalizeAI(Base):
    """파일럿 전용 AI 주석 경로: 값을 바꾸지 않고 옮기며, 확정할 수 없는 값은 거부한다."""

    def test_values_copied_without_change(self):
        rows = filled("AI_DRAFT", {3: {"centrality": "UNSURE", "unsure_reason": "테스트"}})
        s = at.finalize_ai(PID, self.save("ai.csv", rows), self.root / "f")
        final = sc.read_csv(self.root / "f" / f"{PID}_final.csv")
        src = at.candidates(rows)
        self.assertEqual([r["final_centrality"] for r in final],
                         [src[k]["centrality"] for k in sorted(src)])
        self.assertTrue(all(r["h_any"] == r["h_strict"] for r in final))
        self.assertTrue(all(r["adjudication_note"].startswith(at.AI_LABEL) for r in final))
        self.assertEqual((s["h_strict"], s["centrality_unsure_not_H"]), (3, 1))
        self.assertEqual(sc.read_csv(self.root / "f" / f"{PID}_clusters.csv"), [])
        self.assertIn("미주석", s["clusters"])

    def test_rejects_unfinalizable_or_wrong_scope(self):
        with self.assertRaisesRegex(ValueError, "askable UNSURE"):
            at.finalize_ai(PID, self.save("u.csv", filled("AI_DRAFT", {0: {"askable": "UNSURE", "unsure_reason": "x"}})),
                           self.root / "f")
        with self.assertRaisesRegex(ValueError, "파일럿 환자"):
            at.finalize_ai("S002", self.save("c.csv", filled("AI_DRAFT")), self.root / "f")
        with self.assertRaisesRegex(ValueError, "rater_id"):
            at.finalize_ai(PID, self.save("m.csv", filled("AI_DRAFT", {0: {"rater_id": "X"}})), self.root / "f")


if __name__ == "__main__":
    unittest.main(verbosity=2)
