"""Runnable v1 contract examples. All identifiers, scores and text are synthetic."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from check_responses import check_inference, check_patient


AI = {
    "job_id": "JOB_EX_001", "model_version": "test-v1", "preprocess_version": "prep-test",
    "decision": "CANDIDATES", "candidates": [
        {"class_id": "class_a", "score": 0.6}, {"class_id": "class_b", "score": 0.4},
    ],
}
AI_EXPECTED = ("JOB_EX_001", "test-v1", "prep-test", ["class_a", "class_b"])
PATIENT = {
    "case_id": "CASE_EX_001", "case_status": "confirmed",
    "final_text": "합성 예시 소견", "review_comment": "합성 예시 코멘트",
    "confirmed_at": "2026-11-03T01:00:00Z",
}


class ContractTests(unittest.TestCase):
    def test_candidate_and_hold_examples(self):
        check_inference(AI, *AI_EXPECTED)
        for reason in ("LOW_QUALITY", "UNSUPPORTED_INPUT", "LOW_CONFIDENCE"):
            check_inference(dict(AI, decision="HOLD", candidates=[], hold_reason=reason), *AI_EXPECTED)

    def test_inference_rejects_mixed_or_mismatched_results(self):
        cases = [
            {"job_id": "OTHER"}, {"model_version": "old"}, {"preprocess_version": "old"},
            {"decision": "UNKNOWN"}, {"decision": "HOLD", "hold_reason": "LOW_QUALITY"},
            {"decision": "HOLD", "candidates": []}, {"hold_reason": "LOW_QUALITY"},
            {"decision": "HOLD", "candidates": [], "hold_reason": "OTHER"},
            {"candidates": []},
        ]
        for change in cases:
            with self.subTest(change=change), self.assertRaises(ValueError):
                check_inference(dict(AI, **change), *AI_EXPECTED)

    def test_inference_checks_candidate_labels_and_scores(self):
        for label, score in [("class_b", 0.7), ("class_a", 0.4), ("unknown", 0.4),
                             ("class_b", True), ("class_b", "0.4"), ("class_b", float("nan")),
                             ("class_b", float("inf"))]:
            candidates = [AI["candidates"][0], {"class_id": label, "score": score}]
            with self.subTest(label=label, score=score), self.assertRaises(ValueError):
                check_inference(dict(AI, candidates=candidates), *AI_EXPECTED)

    def test_confirmed_result_with_and_without_optional_text(self):
        check_patient(PATIENT, PATIENT["case_id"])
        check_patient(dict(PATIENT, visit_recommendation="테스트 안내",
                           follow_up_instructions="테스트 후속 안내", confirmed_at="2026-11-03T01:00:00.123+00:00"),
                      PATIENT["case_id"])

    def test_unconfirmed_private_or_invalid_fields_are_rejected(self):
        for change in [{"case_id": "OTHER"}, {"case_status": "under_review"}, {"image_url": "fixture"},
                       {"llm_draft": {}}, {"candidates": []}, {"review_comment": "   "},
                       {"visit_recommendation": None}, {"confirmed_at": "2026-02-30T01:00:00Z"},
                       {"confirmed_at": "2026-11-03T10:00:00+09:00"}]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                check_patient(dict(PATIENT, **change), PATIENT["case_id"])
        without_comment = {k: v for k, v in PATIENT.items() if k != "review_comment"}
        with self.assertRaises(ValueError):
            check_patient(without_comment, PATIENT["case_id"])

    def test_forbidden_and_not_ready_have_no_result_fields(self):
        for status, code in [(403, "FORBIDDEN"), (409, "RESULT_NOT_READY")]:
            error = {"request_id": "REQ_TEST", "error": {"code": code, "message": "테스트 오류"}}
            check_patient(error, PATIENT["case_id"], status)
            with self.assertRaises(ValueError):
                check_patient(dict(error, final_text="fixture"), PATIENT["case_id"], status)
            with self.assertRaises(ValueError):
                check_patient(error, PATIENT["case_id"], 409 if status == 403 else 403)

    def test_cli_exit_status_and_private_text(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / "example.json"
            script = Path(__file__).with_name("check_responses.py")
            for response, wanted in [(PATIENT, 0), (dict(PATIENT, image_url="private-sentinel"), 1)]:
                file.write_text(json.dumps(response), encoding="utf-8")
                result = subprocess.run([sys.executable, str(script), "patient", str(file),
                                         "--case-id", PATIENT["case_id"]], capture_output=True, text=True)
                self.assertEqual(result.returncode, wanted)
                self.assertNotIn("private-sentinel", result.stdout + result.stderr)
                self.assertNotIn(PATIENT["case_id"], result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()

