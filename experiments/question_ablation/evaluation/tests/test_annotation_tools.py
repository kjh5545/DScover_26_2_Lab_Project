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


def filled(rater: str, change: dict | None = None) -> list[dict]:
    """원본 주석표의 후보 행에 가짜 값을 채운다. change: {후보 순번: {열: 값}}."""
    rows = sc.read_csv(EVAL / "preannotation" / f"{PID}_preannotation.csv")
    i = 0
    for r in rows:
        if r["is_candidate"] != "1":
            continue
        r.update(askable="ASK_PATIENT", decisiveness="2" if i < 3 else "1", centrality="2" if i < 3 else "0",
                 rationale="테스트 근거", rater_id=rater)
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


class Check(Base):
    def test_blank_template_fails_and_filled_passes(self):
        self.assertTrue(at.check(PID, sc.read_csv(EVAL / "preannotation" / f"{PID}_preannotation.csv")))
        self.assertEqual(at.check(PID, filled("A1")), [])

    def test_rules(self):
        cases = (({0: {"askable": "maybe"}}, "askable 값"),
                 ({0: {"decisiveness": "UNSURE"}}, "판단 불가 사유"),
                 ({0: {"rationale": ""}}, "rationale"),
                 ({0: {"criterion_text": "바꾼 문구"}}, "주어진 열"))
        for change, msg in cases:
            self.assertTrue(any(msg in e for e in at.check(PID, filled("A1", change))), msg)
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


class CompareAndFinalize(Base):
    def pair(self):
        a = self.save("a.csv", filled("A1"))
        b = self.save("b.csv", filled("A2", {0: {"centrality": "1"},            # H 유지 (2+1)
                                              3: {"decisiveness": "2", "centrality": "1"},  # L → H
                                              4: {"askable": "UNSURE", "unsure_reason": "모름"}}))
        return a, b

    def test_compare_counts_and_template(self):
        a, b = self.pair()
        r = at.compare(PID, a, b, self.root / "out")
        self.assertEqual(r["candidates"], 13)
        self.assertEqual((r["H"]["rater1"], r["H"]["rater2"], r["H"]["both"], r["H"]["either_h_any"]), (3, 4, 3, 4))
        self.assertEqual(r["to_adjudicate"], 4)
        self.assertAlmostEqual(r["agreement"]["askable"]["percent"], 12 / 13)
        adj = sc.read_csv(self.root / "out" / f"{PID}_adjudication.csv")
        self.assertEqual({x["field"] for x in adj}, {"askable", "decisiveness", "centrality"})
        self.assertTrue(all(x["final_value"] == "" for x in adj))
        with self.assertRaises(FileExistsError):
            at.compare(PID, a, b, self.root / "out")

    def test_both_unsure_askable_needs_adjudication(self):
        same = {0: {"askable": "UNSURE", "unsure_reason": "모름"}}
        a, b = self.save("a.csv", filled("A1", same)), self.save("b.csv", filled("A2", same))
        r = at.compare(PID, a, b, self.root / "out")
        self.assertEqual(r["to_adjudicate"], 1)

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
        adj = sc.read_csv(adj_path)
        for x in adj:
            x.update(final_value="ASK_RECORD" if x["field"] == "askable" else x["rater1_value"],
                     reason="토의 결과", adjudicator_id="J1")
        sc.write_csv(adj_path, sc.SCHEMA["adjudication_columns"], adj)
        s = at.finalize(PID, a, b, adj_path, self.root / "final")
        self.assertEqual((s["rows"], s["h_strict"], s["h_any"]), (13, 3, 4))
        rows = sc.read_csv(self.root / "final" / f"{PID}_final.csv")
        self.assertEqual(list(rows[0]), sc.SCHEMA["preannotation_final_columns"])
        self.assertEqual(sum(r["final_askable"] == "ASK_RECORD" for r in rows), 1)
        self.assertTrue(any("토의 결과" in r["adjudication_note"] for r in rows))
        with self.assertRaises(FileExistsError):
            at.finalize(PID, a, b, adj_path, self.root / "final")

    def test_finalize_rejects_unsure_askable_and_stale_table(self):
        a, b = self.pair()
        at.compare(PID, a, b, self.root / "out")
        adj_path = self.root / "out" / f"{PID}_adjudication.csv"
        adj = sc.read_csv(adj_path)
        for x in adj:
            x.update(final_value=x["rater2_value"], reason="r", adjudicator_id="J1")
        sc.write_csv(adj_path, sc.SCHEMA["adjudication_columns"], adj)
        with self.assertRaisesRegex(ValueError, "UNSURE"):
            at.finalize(PID, a, b, adj_path, self.root / "final")
        sc.write_csv(adj_path, sc.SCHEMA["adjudication_columns"], adj[:-1])
        with self.assertRaisesRegex(ValueError, "현재 불일치와 다름"):
            at.finalize(PID, a, b, adj_path, self.root / "final")

    def test_score_columns_only_when_requested(self):
        a, b = self.save("a.csv", filled("A1")), self.save("b.csv", filled("A2"))
        at.compare(PID, a, b, self.root / "out")
        s = at.finalize(PID, a, b, self.root / "out" / f"{PID}_adjudication.csv", self.root / "f1", score_columns=True)
        cols = list(sc.read_csv(Path(s["file"]))[0])
        self.assertEqual(cols[-2:], ["final_decisiveness", "final_centrality"])

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
