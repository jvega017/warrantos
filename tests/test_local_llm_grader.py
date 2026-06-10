#!/usr/bin/env python3
"""Tests for provenance.grade.LocalLLMGrader.

The grader posts to an OpenAI-compatible /v1/chat/completions endpoint.
These tests stand up a stdlib http.server in a background thread and
point the grader at it via PROVENANCE_LOCAL_GRADER_URL. No network is
hit; the mock returns canned responses to verify each verdict path.
"""

import json
import os
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, Optional

from warrantos.provenance.grade import (
    HeuristicGrader,
    LocalLLMGrader,
    Verdict,
    get_grader,
)


class _MockResponseQueue:
    """Holds the next response for the mock server to return."""

    def __init__(self) -> None:
        self.next_status: int = 200
        self.next_body: str = ""
        self.last_request_body: Optional[bytes] = None
        self.last_authorization: Optional[str] = None

    def configure(self, *, status: int = 200, body: str = "") -> None:
        self.next_status = status
        self.next_body = body


_QUEUE = _MockResponseQueue()


class _MockHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - http.server signature
        length = int(self.headers.get("Content-Length", "0"))
        _QUEUE.last_request_body = self.rfile.read(length) if length else b""
        _QUEUE.last_authorization = self.headers.get("Authorization")
        self.send_response(_QUEUE.next_status)
        self.send_header("Content-Type", "application/json")
        body = _QUEUE.next_body.encode("utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: Any) -> None:  # silence noise
        return


def _start_server() -> HTTPServer:
    server = HTTPServer(("127.0.0.1", 0), _MockHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _chat_completion_body(*, verdict: str, confidence: float, rationale: str) -> str:
    return json.dumps({
        "id": "test-id",
        "object": "chat.completion",
        "model": "test-local",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": json.dumps({
                        "verdict": verdict,
                        "confidence": confidence,
                        "rationale": rationale,
                    }),
                },
                "finish_reason": "stop",
            }
        ],
    })


class _LocalGraderTestBase(unittest.TestCase):
    """Spins up the mock server and points the grader at it."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.server = _start_server()
        host, port = cls.server.server_address
        cls.endpoint = "http://%s:%d/v1/chat/completions" % (host, port)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()

    def setUp(self) -> None:
        # Set the env var for every test; clear it on tearDown so the
        # selection-order tests can rely on a clean state.
        self._saved_env = {
            "PROVENANCE_LOCAL_GRADER_URL": os.environ.get("PROVENANCE_LOCAL_GRADER_URL"),
            "PROVENANCE_LOCAL_GRADER_MODEL": os.environ.get("PROVENANCE_LOCAL_GRADER_MODEL"),
            "PROVENANCE_LOCAL_GRADER_API_KEY": os.environ.get("PROVENANCE_LOCAL_GRADER_API_KEY"),
            "ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY"),
        }
        for k in ("PROVENANCE_LOCAL_GRADER_API_KEY", "ANTHROPIC_API_KEY"):
            if k in os.environ:
                del os.environ[k]
        os.environ["PROVENANCE_LOCAL_GRADER_URL"] = self.endpoint
        os.environ["PROVENANCE_LOCAL_GRADER_MODEL"] = "test-local"

    def tearDown(self) -> None:
        for k, v in self._saved_env.items():
            if v is None:
                if k in os.environ:
                    del os.environ[k]
            else:
                os.environ[k] = v


class TestLocalLLMGraderVerdicts(_LocalGraderTestBase):
    """Each verdict the local LLM returns is faithfully transcribed."""

    def test_verified_verdict(self):
        _QUEUE.configure(body=_chat_completion_body(
            verdict="verified", confidence=0.91,
            rationale="Source contains the claim's load-bearing tokens.",
        ))
        v = LocalLLMGrader().grade(
            "The Act will save AUD 250 million.",
            source_text="The Act is projected to save AUD 250 million.",
            citation="https://example.invalid/x",
        )
        self.assertIsInstance(v, Verdict)
        self.assertEqual(v.verdict, "verified")
        self.assertAlmostEqual(v.confidence, 0.91)
        self.assertIn("load-bearing tokens", v.rationale)
        self.assertTrue(v.grader.startswith("fetch+local-llm:"))

    def test_contradicted_verdict_via_local_model(self):
        """The reason for the entire LocalLLMGrader: the heuristic
        cannot emit `contradicted` by construction. A local model can."""
        _QUEUE.configure(body=_chat_completion_body(
            verdict="contradicted", confidence=0.85,
            rationale="Source asserts the opposite.",
        ))
        v = LocalLLMGrader().grade(
            "The programme reduced costs by 12 per cent.",
            source_text="The programme increased costs by 8 per cent.",
            citation="https://example.invalid/y",
        )
        self.assertEqual(v.verdict, "contradicted")

    def test_unverifiable_verdict(self):
        _QUEUE.configure(body=_chat_completion_body(
            verdict="unverifiable", confidence=0.4,
            rationale="No source text was supplied.",
        ))
        v = LocalLLMGrader().grade(
            "The Act will save AUD 250 million.",
            source_text=None,
            citation="(Treasury, 2026)",
        )
        self.assertEqual(v.verdict, "unverifiable")
        self.assertEqual(v.grader, "local-llm:test-local")


class TestLocalLLMGraderFallbacks(_LocalGraderTestBase):
    """Any failure falls back to HeuristicGrader; never raises."""

    def test_non_200_falls_back_to_heuristic(self):
        _QUEUE.configure(status=500, body="server error")
        v = LocalLLMGrader().grade(
            "An ordinary claim.", source_text=None, citation=None,
        )
        # Heuristic with no citation and no source text -> skipped.
        self.assertEqual(v.verdict, "skipped")
        self.assertEqual(v.grader, "heuristic")

    def test_malformed_json_falls_back_to_heuristic(self):
        _QUEUE.configure(body='{"choices": [{"message": {"content": "not json at all"}}]}')
        v = LocalLLMGrader().grade(
            "The Act will save 250 million.",
            source_text="The Act will save 250 million.",
            citation="https://example.invalid/z",
        )
        # Heuristic with source text + matching tokens -> verified.
        self.assertEqual(v.verdict, "verified")
        self.assertTrue(v.grader.endswith("heuristic"))

    def test_missing_env_var_falls_back_immediately(self):
        del os.environ["PROVENANCE_LOCAL_GRADER_URL"]
        v = LocalLLMGrader().grade(
            "An ordinary claim.", source_text=None, citation=None,
        )
        self.assertEqual(v.verdict, "skipped")
        self.assertEqual(v.grader, "heuristic")


class TestLocalLLMGraderAuth(_LocalGraderTestBase):
    """The Bearer token is sent only when PROVENANCE_LOCAL_GRADER_API_KEY is set."""

    def test_no_auth_header_by_default(self):
        _QUEUE.configure(body=_chat_completion_body(
            verdict="verified", confidence=0.9, rationale="ok",
        ))
        LocalLLMGrader().grade("c", source_text="c", citation=None)
        self.assertIsNone(_QUEUE.last_authorization)

    def test_auth_header_sent_when_key_set(self):
        os.environ["PROVENANCE_LOCAL_GRADER_API_KEY"] = "sk-local-test"
        try:
            _QUEUE.configure(body=_chat_completion_body(
                verdict="verified", confidence=0.9, rationale="ok",
            ))
            LocalLLMGrader().grade("c", source_text="c", citation=None)
            self.assertEqual(_QUEUE.last_authorization, "Bearer sk-local-test")
        finally:
            del os.environ["PROVENANCE_LOCAL_GRADER_API_KEY"]


class TestGetGraderSelectionOrder(_LocalGraderTestBase):
    """get_grader() picks LocalLLMGrader first when env var is set,
    then LLMGrader, then HeuristicGrader."""

    def test_local_url_wins_over_anthropic_key(self):
        os.environ["ANTHROPIC_API_KEY"] = "sk-anthropic-test"
        try:
            grader = get_grader()
            self.assertIsInstance(grader, LocalLLMGrader)
        finally:
            del os.environ["ANTHROPIC_API_KEY"]

    def test_no_local_url_with_anthropic_key_picks_llm_grader(self):
        del os.environ["PROVENANCE_LOCAL_GRADER_URL"]
        os.environ["ANTHROPIC_API_KEY"] = "sk-anthropic-test"
        try:
            from warrantos.provenance.grade import LLMGrader
            grader = get_grader()
            self.assertIsInstance(grader, LLMGrader)
        finally:
            del os.environ["ANTHROPIC_API_KEY"]

    def test_no_keys_picks_heuristic(self):
        del os.environ["PROVENANCE_LOCAL_GRADER_URL"]
        grader = get_grader()
        self.assertIsInstance(grader, HeuristicGrader)


if __name__ == "__main__":
    unittest.main(verbosity=2)
