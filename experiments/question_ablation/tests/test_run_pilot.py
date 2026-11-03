"""파일럿 실행기 로컬 검증. 외부 API를 부르지 않는다 (mock과 127.0.0.1 가짜 서버만 사용).

실행: python experiments/question_ablation/tests/test_run_pilot.py
"""

import copy
import csv
import hashlib
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE.parent))

import run_pilot as rp  # noqa: E402
import scoring as sc  # noqa: E402


def question_entry(arm="C_full", pid="S004", rep=1):
    return {"run_key": rp.run_key(arm, pid, rep), "arm": arm, "patient_id": pid, "rep": rep,
            "downstream": arm in rp.CORE_ARMS}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.ws = rp.Workspace(self.root / "exp", mock=True)
        self.prompts = rp.load_prompts()

    def tearDown(self):
        self.tmp.cleanup()

    def real_annotation(self, base: Path):
        """모집단 검사를 통과하는 가상 확정 주석 (테스트 전용)."""
        base.mkdir(parents=True, exist_ok=True)
        for pid in rp.PATIENTS:
            b = rp.make_bundle(pid)
            rows = [{"patient_id": pid, "trial_id": m["trial"], "criterion_id": m["criterion_id"],
                     "final_askable": "NOT_OBTAINABLE" if i == 0 else "ASK_PATIENT", "final_tier": "H" if i < 4 else "L",
                     "h_strict": "true" if 0 < i < 4 else "false", "h_any": "true" if 0 < i < 5 else "false",
                     "adjudication_note": "테스트"}
                    for i, m in enumerate(rp.qb.collect_materials(b))]
            sc.write_csv(base / f"{pid}_final.csv", sc.SCHEMA["preannotation_final_columns"], rows)
            sc.write_csv(base / f"{pid}_clusters.csv", sc.SCHEMA["cluster_columns"], [])
        draft = base / "draft.json"
        draft.write_text(json.dumps({"m4a_definition_review": {"approved": True}, "judge_freeze_confirmed_by": ["테스트"],
                                     "people": [{"id": "R1", "gold_exposed": "none"}]}), encoding="utf-8")
        return draft


class Plan(Base):
    def test_all_prompts_load(self):
        self.assertEqual(set(self.prompts), set(rp.ARMS))

    def test_plan_has_thirty_runs(self):
        plan = rp.make_plan()
        self.assertEqual(len(plan), 30)
        self.assertEqual(len({e["run_key"] for e in plan}), 30)
        self.assertEqual(sum(e["downstream"] for e in plan), 24)
        self.assertEqual(Counter(e["arm"] for e in plan), {a: 6 for a in rp.ARMS})
        self.assertFalse(any(e["downstream"] for e in plan if e["arm"] == "A2s"))

    def test_plan_is_reproducible_and_blocked_by_rep(self):
        plan = rp.make_plan()
        self.assertEqual(plan, rp.make_plan())
        self.assertNotEqual(plan, rp.make_plan(seed=1))
        self.assertEqual([e["rep"] for e in plan], [1] * 10 + [2] * 10 + [3] * 10)

    def test_inputs_identical_across_arms(self):
        for pid, n in (("S004", 13), ("S008", 23)):
            t = rp.MockTransport()
            for arm in rp.ARMS:
                rp.run_question(question_entry(arm, pid), self.prompts, self.ws, t)
            self.assertEqual(len({c["user"] for c in t.calls}), 1)
            self.assertEqual(len({c["system"] for c in t.calls}), 5)
            self.assertIn("최대 5개", t.calls[0]["user"])

    def test_denominators(self):
        d = rp.denominators()
        self.assertEqual((d["S004"]["candidates_U"], d["S008"]["candidates_U"]), (13, 23))
        self.assertEqual((d["S004"]["criteria"], d["S008"]["criteria"]), (19, 27))
        self.assertEqual((d["S004"]["M8a_denominator"], d["S004"]["M8b_denominator"], d["S004"]["M8d_denominator"]), (6, 7, 6))
        self.assertEqual((d["S008"]["M8a_denominator"], d["S008"]["M8b_denominator"], d["S008"]["M8d_denominator"]), (9, 14, 4))


class Integrity(Base):
    def test_prompt_tamper_detected(self):
        real = Path.read_bytes
        def tampered(path):
            data = real(path)
            return data + b" " if path.name == "A2_no_grouping.txt" else data
        with mock.patch.object(Path, "read_bytes", tampered):
            with self.assertRaises(rp.GateError):
                rp.load_prompts()

    def test_config_changes_detected(self):
        pinned = {"versions": rp.compute_versions()}
        for label, change in (("판정 프롬프트", lambda v: v.update(judge_prompt_sha256="x")),
                              ("시뮬레이터", lambda v: v.update(simulator_prompt_sha256="x")),
                              ("모델", lambda v: v.update(model_id="other")),
                              ("판정 코드", lambda v: v["file_blobs"].update({"src/agents/matcher.py": "x"})),
                              ("Fact Sheet", lambda v: v["file_blobs"].update(
                                  {"screening/detailed/인선/S004_detailed_sheet_filled.md": "x"})),
                              ("입력", lambda v: v["input_sha256"].update(S004="x"))):
            data = copy.deepcopy(pinned)
            change(data["versions"])
            lock = self.root / f"lock{label}.json"
            lock.write_text(json.dumps(data), encoding="utf-8")
            with mock.patch.object(rp, "LOCK", lock), self.assertRaises(rp.GateError, msg=label):
                rp.verify_versions()

    def test_workspace_rejects_changed_plan_and_mock_mix(self):
        plan = rp.make_plan()
        v = rp.compute_versions()
        self.ws.prepare(plan, v)
        self.ws.prepare(plan, v)
        with self.assertRaises(rp.GateError):
            self.ws.prepare(plan[:-1], v)
        with self.assertRaises(rp.GateError):
            self.ws.prepare(plan, {**v, "model_id": "other"})
        with self.assertRaises(rp.GateError):
            rp.Workspace(self.ws.root, mock=False).prepare(plan, v)
        self.assertIn("sealed/", (self.ws.root / ".gitignore").read_text(encoding="utf-8"))

    def test_write_new_never_overwrites(self):
        p = self.root / "a.json"
        rp.write_new(p, {"a": 1})
        with self.assertRaises(FileExistsError):
            rp.write_new(p, {"a": 2})
        self.assertEqual(rp.read_json(p), {"a": 1})


class Execution(Base):
    def run_one(self, faults=None, **kw):
        t = rp.MockTransport(faults)
        return rp.run_question(question_entry(**kw), self.prompts, self.ws, t), t

    def test_raw_and_arranged_saved_separately(self):
        status, _ = self.run_one()
        self.assertEqual(status, "ok")
        r = rp.read_json(self.ws.questions / "C_full__S004__r1.json")
        self.assertGreater(len(r["raw_questions"]), len(r["final_questions"]))
        self.assertLessEqual(len(r["final_questions"]), 5)
        reasons = Counter(x["status"] for x in r["arrange_report"])
        self.assertEqual(reasons["kept"], len(r["final_questions"]))
        self.assertGreaterEqual(reasons["removed_no_valid_criterion"], 1)
        self.assertGreaterEqual(reasons["removed_duplicate_criteria"], 1)
        self.assertGreaterEqual(reasons["removed_over_budget"], 1)
        self.assertIn("missing", r["not_asked_report"])
        self.assertEqual(len(r["d9_hangul_ratio"]), len(r["final_questions"]))
        raw = rp.read_json(next(self.ws.attempts.glob("*.json")))
        self.assertIn("(MOCK)", raw["text"])

    def test_format_failure_retries_once(self):
        for i, fault in enumerate(("bad_json", "truncate", "schema"), 1):
            status, t = self.run_one({1: fault}, rep=i)
            self.assertEqual((status, len(t.calls)), ("ok", 2), fault)
        r = rp.read_json(self.ws.questions / "C_full__S004__r2.json")
        self.assertEqual([c["attempt"] for c in r["calls"]], [1, 2])
        self.assertEqual(r["calls"][0]["stop_reason"], "max_tokens")

    def test_two_format_failures_stop_without_redraw(self):
        status, t = self.run_one({1: "bad_json", 2: "bad_json"})
        self.assertEqual((status, len(t.calls)), ("failed_format", 2))
        status, t2 = self.run_one({1: "bad_json"})
        self.assertEqual((status, len(t2.calls)), ("skipped", 0))
        self.assertEqual(len(list(self.ws.attempts.glob("*.json"))), 2)

    def test_retry_limit_survives_restart(self):
        rec = rp.Recorder(self.ws, rp.MockTransport({1: "bad_json"}), "C_full__S004__r1")
        rec.stage = "question"
        rp.write_new(self.ws.attempts / "C_full__S004__r1__question__001.json", {"format_error": "x"})
        rp.write_new(self.ws.attempts / "C_full__S004__r1__question__002.json", {"format_error": "x"})
        with self.assertRaises(rp.FormatExhausted):
            rec("s", "u")
        self.assertEqual(len(rec.transport.calls), 0)

    def test_refusal_is_recorded_not_retried(self):
        status, t = self.run_one({1: "refusal"})
        self.assertEqual((status, len(t.calls)), ("refused", 1))
        self.assertEqual(rp.read_json(self.ws.questions / "C_full__S004__r1.json")["status"], "refused")

    def test_resume_after_interruption(self):
        plan = rp.make_plan()
        ws, t = self.ws, rp.MockTransport()
        ws.prepare(plan, rp.compute_versions())
        self.assertEqual(rp.execute("questions", plan, ws, t, stop_after=7)["ok"], 7)
        t2 = rp.MockTransport()
        done = rp.execute("questions", plan, ws, t2)
        self.assertEqual((done["skipped"], done["ok"], len(t2.calls)), (7, 23, 23))
        self.assertEqual(len(list(ws.questions.glob("*.json"))), 30)

    def test_api_error_leaves_no_result_and_resumes(self):
        plan = rp.make_plan()[:2]
        t = rp.MockTransport({1: "api_error"})
        done = rp.execute("questions", plan, self.ws, t)
        self.assertEqual((done["api_error"], done["ok"]), (1, 1))
        self.assertFalse((self.ws.questions / f"{plan[0]['run_key']}.json").exists())
        self.assertEqual(rp.execute("questions", plan, self.ws, rp.MockTransport())["ok"], 1)
        self.assertIn("api_error", self.ws.errors.read_text(encoding="utf-8"))

    def test_api_error_streak_stops_paid_loop(self):
        t = rp.MockTransport({i: "api_error" for i in range(1, 31)})
        with self.assertRaises(rp.GateError):
            rp.execute("questions", rp.make_plan(), self.ws, t)
        self.assertEqual(len(t.calls), rp.MAX_API_ERROR_STREAK)

    def test_program_bug_is_not_hidden_as_api_error(self):
        def broken(system, user):
            raise KeyError("bug")
        with self.assertRaises(KeyError):
            rp.execute("questions", rp.make_plan()[:1], self.ws, broken)

    def test_no_llm_module_is_left_patched(self):
        before = rp.qb.ask_json, rp.simulator.ask_json, rp.matcher.ask_json
        self.run_one()
        self.assertEqual(before, (rp.qb.ask_json, rp.simulator.ask_json, rp.matcher.ask_json))

    def test_arrange_report_detects_mismatch(self):
        with self.assertRaises(rp.GateError):
            rp.arrange_report([{"text": "x", "resolves": []}], [], [{"text": "다른 질문"}])

    def test_hangul_threshold_is_diagnostic_only(self):
        t = rp.MockTransport()
        t._questions = lambda user: json.dumps({"questions": [
            {"question": "Do you have hematuria?", "needed_info": "x",
             "resolves": [{"trial": "NCT04369560", "criteria": ["I3"]}]}], "not_asked": []})
        self.assertEqual(rp.run_question(question_entry(), self.prompts, self.ws, t), "ok")
        r = rp.read_json(self.ws.questions / "C_full__S004__r1.json")
        self.assertEqual((r["d9_below_heuristic"], len(t.calls)), (1, 1))


class Downstream(Base):
    def prepared(self, faults=None, arm="C_full", pid="S004"):
        t = rp.MockTransport()
        e = question_entry(arm, pid)
        rp.run_question(e, self.prompts, self.ws, t)
        return e, rp.MockTransport(faults)

    def test_saves_both_stages_and_raw_answers(self):
        e, t = self.prepared()
        self.assertEqual(rp.run_downstream(e, self.ws, t), "ok")
        d = rp.read_json(self.ws.downstream / f"{e['run_key']}.json")
        self.assertEqual(len(d["after_reassess"]), 19)
        self.assertEqual(len(d["after_final"]), 19)
        a = rp.read_json(self.ws.answers / f"{e['run_key']}.json")
        self.assertEqual(len(a["answers"]), len(a["questions"]))
        self.assertIn("(MOCK)", a["answers"][0]["answer"])

    def test_a2s_never_runs_downstream(self):
        e, t = self.prepared(arm="A2s")
        with self.assertRaises(rp.GateError):
            rp.run_downstream(e, self.ws, t)
        self.assertEqual(len(t.calls), 0)
        self.assertEqual(rp.execute("downstream", [e], self.ws, t), Counter())

    def test_simulator_count_and_order_checked(self):
        for i, fault in enumerate(("short", "swap"), 1):
            e, t = self.prepared(pid="S004" if i == 1 else "S008")
            self.assertEqual(rp.run_downstream(e, self.ws, t), "ok")
            e2 = question_entry("A1", "S004", i)
            rp.run_question(e2, self.prompts, self.ws, rp.MockTransport())
            t = rp.MockTransport({1: fault, 2: fault})
            self.assertEqual(rp.run_downstream(e2, self.ws, t), "failed_format", fault)
            self.assertEqual(len(t.calls), 2)

    def test_check_answers(self):
        qs = ["담배를 피우시나요?", "혈뇨가 있었나요?"]
        ok = [{"question": q, "answer": "네"} for q in qs]
        rp.check_answers(qs, ok)
        for bad in (ok[:1], ok[::-1], [ok[0], {"question": qs[1], "answer": " "}], "x"):
            with self.assertRaises(rp.FormatFailure):
                rp.check_answers(qs, bad)

    def test_simulator_checkpoint_reused_on_resume(self):
        e, _ = self.prepared()
        t = rp.MockTransport()
        rp.write_new(self.ws.answers / f"{e['run_key']}.json", {"run_key": e["run_key"], "questions": [],
                     "answers": [{"answer": "저장된 답"}] * 5})
        self.assertEqual(rp.run_downstream(e, self.ws, t), "ok")
        self.assertFalse(any("role-playing" in c["system"] for c in t.calls))

    def test_missing_questions_do_not_trigger_calls(self):
        t = rp.MockTransport()
        self.assertEqual(rp.run_downstream(question_entry(), self.ws, t), "no_questions")
        self.assertEqual(len(t.calls), 0)


class Leakage(Base):
    def test_question_stage_cannot_read_gold_or_facts(self):
        with mock.patch.object(rp, "load_sheet", side_effect=AssertionError("정답 시트 접근")):
            status = rp.run_question(question_entry(pid="S008"), self.prompts, self.ws, rp.MockTransport())
        self.assertEqual(status, "ok")

    def test_fact_text_only_reaches_simulator(self):
        e = question_entry()
        rp.run_question(e, self.prompts, self.ws, rp.MockTransport())
        t = rp.MockTransport()
        rp.run_downstream(e, self.ws, t)
        fact = rp.load_sheet("S004")["detailed_text"]
        marker = "walks about three miles"
        self.assertIn(marker, fact)
        for c in t.calls:
            self.assertEqual(marker in c["user"], "role-playing a PATIENT" in c["system"])
        for f in list(self.ws.questions.glob("*")) + list(self.ws.answers.glob("*")) + list(self.ws.downstream.glob("*")):
            self.assertNotIn(marker, f.read_text(encoding="utf-8"), f.name)

    def test_rater_packet_has_no_condition_or_gold(self):
        rp.execute("questions", rp.make_plan()[:10], self.ws, rp.MockTransport())
        rp.build_rater_packet(self.ws, seed=5)
        fact = "walks about three miles"
        for f in self.ws.packet.iterdir():
            text = f.read_text(encoding="utf-8-sig")
            for token in ("C_full", "A2s", "__r", '"arm"', '"rep"', "not_asked", "attempt", fact):
                self.assertNotIn(token, text, f.name)
        for name in ("question_sheet.csv", "link_sheet.csv"):
            with open(self.ws.packet / name, encoding="utf-8-sig") as fh:
                self.assertFalse(set(next(csv.reader(fh))) & set(sc.SCHEMA["forbidden_in_rater_packet"]))
        self.assertTrue((self.ws.sealed / "blind_map.json").exists())


class PaidGate(Base):
    def args(self, paid="exp1"):
        return types.SimpleNamespace(experiment="exp1", paid=paid)

    def locked_env(self):
        base = self.root / "ann"
        draft = self.real_annotation(base)
        return base, draft

    def test_paid_blocked_without_annotation_lock(self):
        with mock.patch.object(rp, "ANNOTATION_RECORD", self.root / "none.json"):
            with self.assertRaisesRegex(rp.GateError, "사전 주석"):
                rp.paid_gate(self.args())

    def test_paid_needs_explicit_experiment_id(self):
        with self.assertRaisesRegex(rp.GateError, "--paid"):
            rp.paid_gate(self.args(paid="yes"))

    def test_dry_run_allowed_without_lock_or_key(self):
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(rp, "ANNOTATION_RECORD", self.root / "none.json"):
            with mock.patch.object(rp, "RealTransport", side_effect=AssertionError("실제 호출")):
                r = rp.cmd_dry_run(self.root / "dry")
        self.assertTrue(r["mock"])
        self.assertEqual(r["blind_sets"], 30)
        self.assertEqual(r["questions"], {"ok": 30})
        self.assertEqual(r["downstream"], {"ok": 24})
        self.assertIn("차단", r["paid_gate"]["annotation"])

    def test_lock_passes_only_when_complete(self):
        base, draft = self.locked_env()
        rec = rp.lock_annotation(draft, base / "annotation_record.json")
        self.assertEqual(len(rec["files"]), 4)
        rp.annotation_gate(base / "annotation_record.json")

    def test_annotation_tamper_detected(self):
        base, draft = self.locked_env()
        rp.lock_annotation(draft, base / "annotation_record.json")
        with open(base / "S004_final.csv", "a", encoding="utf-8") as f:
            f.write("x\n")
        with self.assertRaisesRegex(rp.GateError, "잠긴 파일"):
            rp.annotation_gate(base / "annotation_record.json")

    def test_lock_record_cannot_be_overwritten(self):
        base, draft = self.locked_env()
        rp.lock_annotation(draft, base / "annotation_record.json")
        with self.assertRaises(FileExistsError):
            rp.lock_annotation(draft, base / "annotation_record.json")

    def test_review_and_people_required(self):
        for change, msg in ((lambda d: d["m4a_definition_review"].update(approved=False), "M4a"),
                            (lambda d: d.update(judge_freeze_confirmed_by=[]), "판정기"),
                            (lambda d: d.update(people=[{"id": "R1"}]), "정답 노출")):
            draft = self.real_annotation(self.root / f"a{msg}")
            data = json.loads(draft.read_text(encoding="utf-8"))
            change(data)
            draft.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(rp.GateError, msg):
                rp.lock_annotation(draft, draft.parent / "annotation_record.json")

    def test_population_mismatch_blocked(self):
        rows = sc.read_csv(self.real_annotation(self.root / "p").parent / "S004_final.csv")
        self.assertTrue(rp.check_annotation_population("S004", rows[:-1]))
        all_criteria = rows + [{**rows[0], "criterion_id": "I1"}]
        self.assertTrue(rp.check_annotation_population("S004", all_criteria))
        self.assertEqual(rp.check_annotation_population("S004", rows), [])

    def test_gold_exposure_changes_blind_label(self):
        reg = self.root / "reg.csv"
        cols = sc.SCHEMA["rater_registry_columns"]
        sc.write_csv(reg, cols, [{"rater_id": "R1", "role": "rater", "gold_exposed": "none", "exposure_scope": "", "note": ""}])
        self.assertTrue(rp.blind_status(reg)["independent_gold_blind"])
        sc.write_csv(reg, cols, [{"rater_id": "R1", "role": "rater", "gold_exposed": "partial", "exposure_scope": "S004", "note": ""}])
        self.assertFalse(rp.blind_status(reg)["independent_gold_blind"])
        self.assertFalse(rp.blind_status(None)["independent_gold_blind"])


class ScoringChain(Base):
    """채점표 생성 → 평가자 2명 → 조정 → 잠금 → 공개 → 지표. 값은 자동 입력한 가짜 채점이다."""

    def fill(self, src: Path, dst: Path, rater: str):
        q, l = sc.read_csv(src / "question_sheet.csv"), sc.read_csv(src / "link_sheet.csv")
        for r in q:
            r.update(assumption="PASS", redundancy="PASS", single_topic="PASS", rater_id=rater,
                     overgroup="NA" if int(r["n_links"]) < 2 else "PASS")
        for r in l:
            r.update(preservation="PASS", coverage="FULL", rater_id=rater,
                     group_validity="NA" if r["is_multi_link"] == "0" else "VALID")
        sc.write_csv(dst / "question_sheet.csv", sc.QC, q)
        sc.write_csv(dst / "link_sheet.csv", sc.LC, l)
        return q, l

    def build(self):
        plan = rp.make_plan()
        self.ws.prepare(plan, rp.compute_versions())
        t = rp.MockTransport()
        rp.execute("questions", plan, self.ws, t)
        rp.execute("downstream", plan, self.ws, t)
        rp.build_rater_packet(self.ws, seed=9)
        self.fill(self.ws.packet, self.root / "r1", "R1")
        self.fill(self.ws.packet, self.root / "r2", "R2")

    def test_full_chain(self):
        self.build()
        l2 = sc.read_csv(self.root / "r2" / "link_sheet.csv")
        l2[0].update(coverage="PARTIAL", error_codes="C2", rationale="일부")
        sc.write_csv(self.root / "r2" / "link_sheet.csv", sc.LC, l2)
        result = rp.compare_raters(self.root / "r1", self.root / "r2", self.ws.scores)
        self.assertEqual(result["disagreements"], 1)
        with self.assertRaisesRegex(rp.GateError, "조정되지"):
            rp.merge_scores(self.root / "r1", self.ws.scores / "adjudication.csv", self.ws.scores)
        adj = sc.read_csv(self.ws.scores / "adjudication.csv")
        adj[0]["final_value"] = "FULL"
        sc.write_csv(self.ws.scores / "adjudication.csv", sc.SCHEMA["adjudication_columns"], adj)
        rp.merge_scores(self.root / "r1", self.ws.scores / "adjudication.csv", self.ws.scores)
        finals = [self.ws.scores / "question_final.csv", self.ws.scores / "link_final.csv"]

        base = self.root / "ann"
        self.real_annotation(base)
        with mock.patch.object(rp, "gold_of", side_effect=AssertionError("잠금 전 정답 접근")):
            with self.assertRaises(PermissionError):
                rp.report(self.ws, base, None, None)
        with self.assertRaises(PermissionError):
            rp.sim_audit_sheet(self.ws)

        sc.lock(self.ws.sealed, finals)
        audit = rp.sim_audit_sheet(self.ws)
        rows = sc.read_csv(audit)
        self.assertLessEqual({r["audit_id"].split("#")[0] for r in rows}, {r["blind_id"] for r in sc.read_csv(finals[0])})
        rows[0]["simulator_code"] = "S1"
        sc.write_csv(audit, sc.SCHEMA["simulator_audit_columns"], rows)

        out = rp.report(self.ws, base, None, audit)
        self.assertTrue(out["mock"])
        self.assertFalse(out["blinding"]["independent_gold_blind"])
        self.assertEqual(len(out["question_metrics"]), 10)
        self.assertEqual(len(out["downstream_metrics"]), 8)
        cell = out["question_metrics"]["S004|C_full"]
        self.assertEqual((cell["M1a"]["mean"], cell["M2"]["mean"], cell["M1a"]["n"]), (1.0, 0.0, 3))
        self.assertAlmostEqual(cell["M3a"]["mean"], cell["M3b"]["mean"])
        self.assertIsNotNone(cell["M7a"])
        self.assertNotIn("S004|A2s", out["downstream_metrics"])
        self.assertEqual(out["downstream_metrics"]["S004|C_full"]["final.M8a"]["max"], 0.0)

    def test_locked_scores_cannot_change_before_report(self):
        self.build()
        rp.merge_scores(self.root / "r1", self.root / "none.csv", self.ws.scores)
        finals = [self.ws.scores / "question_final.csv", self.ws.scores / "link_final.csv"]
        sc.lock(self.ws.sealed, finals)
        with open(finals[1], "a", encoding="utf-8") as f:
            f.write("x")
        with self.assertRaises(PermissionError):
            rp.report(self.ws, self.root / "ann", None, None)

    def test_invalid_scores_cannot_be_merged(self):
        self.build()
        l = sc.read_csv(self.root / "r1" / "link_sheet.csv")
        l[0]["coverage"] = "NONE"
        sc.write_csv(self.root / "r1" / "link_sheet.csv", sc.LC, l)
        with self.assertRaisesRegex(rp.GateError, "형식 오류"):
            rp.merge_scores(self.root / "r1", self.root / "none.csv", self.ws.scores)


class Handler(http.server.BaseHTTPRequestHandler):
    seen = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        Handler.seen.append(body)
        data = json.dumps({"id": "msg_test", "type": "message", "role": "assistant", "model": body["model"],
                           "content": [{"type": "thinking", "thinking": "", "signature": "s"},
                                       {"type": "text", "text": '{"questions": [], "not_asked": []}'}],
                           "stop_reason": "end_turn", "stop_sequence": None,
                           "usage": {"input_tokens": 100, "output_tokens": 50}}).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("request-id", "req_test")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


class SdkShape(Base):
    """실제 SDK를 쓰되 127.0.0.1의 가짜 서버로 보낸다. 외부 API는 호출하지 않는다."""

    def test_real_transport_request_and_response(self):
        try:
            import anthropic
        except ImportError:
            self.skipTest("SDK 없음")
        if getattr(anthropic, "__version__", None) is None:
            self.skipTest("SDK 없음 (스텁)")
        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            client = anthropic.Anthropic(api_key="test-not-a-key", base_url=f"http://127.0.0.1:{server.server_port}",
                                         max_retries=0)
            reply = rp.RealTransport(client)("시스템", "사용자")
        finally:
            server.shutdown()
        sent = Handler.seen[-1]
        self.assertEqual(sent["model"], "claude-sonnet-5-5")
        self.assertEqual(sent["max_tokens"], 16000)
        self.assertEqual(sent["thinking"], {"type": "adaptive"})
        self.assertEqual(set(sent), {"model", "max_tokens", "thinking", "system", "messages"})
        self.assertEqual((reply["input_tokens"], reply["output_tokens"], reply["stop_reason"]), (100, 50, "end_turn"))
        self.assertEqual(json.loads(reply["text"]), {"questions": [], "not_asked": []})
        self.assertEqual(reply["model"], "claude-sonnet-5-5")


class Estimate(unittest.TestCase):
    def test_counts(self):
        e = rp.estimate()
        self.assertEqual(e["lines"]["question"]["calls"], [30, 30])
        self.assertEqual(e["lines"]["simulator"]["calls"], [24, 24])
        self.assertEqual(e["lines"]["reassess"]["calls"], [24, 48])
        self.assertEqual(e["lines"]["final_check"]["calls"], [48, 48])
        self.assertEqual(e["total_calls"], [126, 150])

    def test_price_matches_repository(self):
        self.assertEqual(rp.estimate()["price_per_mtok"], (2.0, 10.0))


class Repository(Base):
    def test_shared_files_unchanged_by_full_mock_run(self):
        def state():
            out = subprocess.run(["git", "status", "--porcelain"], cwd=rp.ROOT, capture_output=True, text=True,
                                 encoding="utf-8").stdout
            return [x for x in out.splitlines() if "experiments/question_ablation" not in x]
        before = state()
        rp.cmd_dry_run(self.root / "dry")
        self.assertEqual(before, state())
        self.assertEqual(before, [])

    def test_runner_does_not_call_overwriting_helpers(self):
        src = (HERE.parent / "run_pilot.py").read_text(encoding="utf-8")
        for name in ("run_loop(", "save_bundle(", "save=True", "run_intake("):
            self.assertNotIn(name, src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
