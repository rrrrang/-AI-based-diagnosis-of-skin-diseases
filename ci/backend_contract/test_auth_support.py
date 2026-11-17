"""Fail-closed checks for test credentials; no API or deployed service used."""
import json
from pathlib import Path
import tempfile
import unittest

if __package__:
    from .auth_support import (DOCTOR_TOKENS_ENV, bearer_headers, doctor_environment,
                               load_doctor_tokens, new_doctor_tokens, patient_headers,
                               patient_token)
else:
    from auth_support import (DOCTOR_TOKENS_ENV, bearer_headers, doctor_environment,
                              load_doctor_tokens, new_doctor_tokens, patient_headers,
                              patient_token)


class AuthSupportTests(unittest.TestCase):
    def test_intentional_anonymous_request_has_no_auth_header(self):
        self.assertEqual(bearer_headers(None), {})

    def test_missing_or_invalid_patient_token_never_becomes_anonymous(self):
        for body in (None, {}, {"accessToken": None}, {"accessToken": ""},
                     {"accessToken": 123}, {"accessToken": "invalid token"}):
            with self.subTest(kind=type(body).__name__):
                with self.assertRaises(ValueError):
                    patient_headers(body)

    def test_headers_and_case_tokens_are_independent(self):
        first = {"id": "CASE-first", "accessToken": "case-first"}
        second = {"id": "CASE-second", "accessToken": "case-second"}
        self.assertEqual(patient_token(first), "case-first")
        headers = patient_headers(first)
        headers["Authorization"] = "changed"
        self.assertEqual(patient_headers(first), {"Authorization": "Bearer case-first"})
        self.assertEqual(patient_headers(second), {"Authorization": "Bearer case-second"})

    def test_header_injection_is_rejected_without_echoing_token(self):
        secret = "private-marker\r\nInjected: yes"
        with self.assertRaises(ValueError) as caught:
            bearer_headers(secret)
        self.assertNotIn("private-marker", str(caught.exception))

    def test_generated_doctor_credentials_are_per_run_and_separate(self):
        first, second = new_doctor_tokens(), new_doctor_tokens()
        self.assertEqual(set(first), {"d1", "d2"})
        self.assertEqual(len(set([*first.values(), *second.values()])), 4)
        self.assertEqual(set(new_doctor_tokens(("d1",))), {"d1"})

    def test_invalid_doctor_settings_are_rejected(self):
        for tokens in ({}, {"d1": ""}, {"d1": "same", "d2": "same"},
                       {"d1": "valid", "d2": 123}, {"bad identity": "valid"}):
            with self.subTest(count=len(tokens)):
                with self.assertRaises(ValueError):
                    doctor_environment(tokens)
        for identities in (("d1", "d1"), ("invalid identity",), (None,), ([],)):
            with self.assertRaises(ValueError):
                new_doctor_tokens(identities)

    def test_explicit_env_file_round_trip_supports_bom(self):
        tokens = new_doctor_tokens()
        settings = doctor_environment(tokens)
        self.assertEqual(set(settings), {DOCTOR_TOKENS_ENV})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "temporary-doctor-test.env"
            path.write_text(DOCTOR_TOKENS_ENV + "=" + settings[DOCTOR_TOKENS_ENV] + "\n",
                            encoding="utf-8-sig")
            self.assertTrue(load_doctor_tokens(path) == tokens, "Test credential round-trip mismatch")

    def test_env_file_failures_are_closed_and_do_not_echo_credentials(self):
        marker = "private-test-marker"
        invalid = (
            "", DOCTOR_TOKENS_ENV + '=broken-' + marker,
            DOCTOR_TOKENS_ENV + '=' + json.dumps({"d1": marker}),
            DOCTOR_TOKENS_ENV + '=' + json.dumps({"d1": marker, "d2": marker}),
            DOCTOR_TOKENS_ENV + '={"d1":"' + marker + '","d1":"again","d2":"second"}',
            (DOCTOR_TOKENS_ENV + '={"d1":"first","d2":"second"}\n') * 2,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "temporary-doctor-test.env"
            for content in invalid:
                path.write_text(content, encoding="utf-8")
                with self.assertRaises(ValueError) as caught:
                    load_doctor_tokens(path)
                self.assertNotIn(marker, str(caught.exception))
                self.assertTrue(caught.exception.__suppress_context__)
            with self.assertRaises(ValueError):
                load_doctor_tokens(Path(directory) / "missing.env")


if __name__ == "__main__":
    unittest.main(verbosity=2)
