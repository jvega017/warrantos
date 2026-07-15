"""provenance.grade: heuristic and LLM-based claim graders.

Provides two grader classes and a Verdict dataclass. The graders implement
Axis 2 verdict classification (verified, contradicted, not_addressed,
unverifiable, skipped, error). Axis 1 (supported/tagged/unsupported) remains
in the hook and is not modified here.

The LLM grader is optional. It is activated only when the environment variable
ANTHROPIC_API_KEY is set, and degrades gracefully to the heuristic on ANY
failure (missing key, network error, non-200 response, JSON parse failure).
The hook is never called from this module: this is strictly out-of-band.

Stdlib only: urllib, json, os, re, dataclasses, typing. No third-party packages.
Python 3.8 compatible.

Australian English throughout.
"""

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional

# ---------------------------------------------------------------------------
# Verdict dataclass — shared interface contract for Agents 2-4
# ---------------------------------------------------------------------------

@dataclass
class Verdict:
    """The result of grading a single claim against its cited source.

    Attributes
    ----------
    claim_text:
        The full text of the sentence that contains the factual claim.
    citation:
        The URL or APA reference string extracted from the claim sentence,
        or None if no citation was found.
    verdict:
        One of: verified | contradicted | not_addressed |
                unverifiable | skipped | error.
    confidence:
        Float 0.0-1.0 when a grader can express confidence; None otherwise.
    rationale:
        Human-readable explanation, at most 200 characters, plain text.
    grader:
        Which grader produced this result. One of:
        heuristic | fetch+heuristic | llm:<model> | fetch+llm:<model>.
    """

    claim_text: str
    citation: Optional[str]
    verdict: str
    confidence: Optional[float]
    rationale: str
    grader: str


# ---------------------------------------------------------------------------
# Salient-token extraction for heuristic matching
# ---------------------------------------------------------------------------

# Patterns that identify tokens worth checking (numbers, years, percentages,
# and longer content words).
_NUMBER_TOKEN = re.compile(r"\b\d[\d,./%-]*\b")
_YEAR_TOKEN = re.compile(r"\b(?:18|19|20)\d{2}\b")
_PCT_TOKEN = re.compile(r"\b\d+(?:\.\d+)?\s?%|\bper\s?cent\b|\bpercent\b", re.I)


_URL_STRIP = re.compile(r"https?://\S+", re.I)


def _salient_tokens(claim_text: str):
    """Return a list of tokens that are worth checking in the source text.

    Includes: all digit sequences, 4-digit years, percentage expressions,
    and content words of 6 or more characters (excluding common function
    words). URLs are stripped from the claim before extraction so that
    URL hostnames and paths do not contribute noise tokens.
    """
    # Strip embedded URLs before extracting tokens so that URL components
    # (hostnames, path segments) are not treated as salient content tokens.
    claim_text = _URL_STRIP.sub("", claim_text)

    tokens = []

    # Numeric and percentage tokens.
    for m in _NUMBER_TOKEN.finditer(claim_text):
        tokens.append(m.group(0).lower())
    for m in _PCT_TOKEN.finditer(claim_text):
        tokens.append(m.group(0).lower())

    # Longer content words (>=6 chars) to catch distinctive terminology.
    _STOP = {
        "according", "because", "however", "although", "through",
        "within", "between", "before", "during", "against",
        "should", "would", "could", "might", "their", "which",
        "there", "where", "these", "those", "other",
    }
    for word in re.findall(r"\b[a-zA-Z]{6,}\b", claim_text):
        if word.lower() not in _STOP:
            tokens.append(word.lower())

    # Deduplicate while preserving order.
    seen = set()
    result = []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            result.append(t)
    return result


# ---------------------------------------------------------------------------
# HeuristicGrader
# ---------------------------------------------------------------------------

class HeuristicGrader:
    """Token-overlap heuristic grader. No network I/O. Stdlib only."""

    def grade(
        self,
        claim_text: str,
        source_text: Optional[str],
        citation: Optional[str],
    ) -> Verdict:
        """Grade a claim against optional source text.

        Parameters
        ----------
        claim_text:
            The sentence asserting the fact.
        source_text:
            The text fetched from the citation URL, or None if not fetched.
        citation:
            The raw citation string from the claim sentence (URL or APA ref).

        Returns
        -------
        Verdict
            verdict="verified" when salient tokens are present in source_text;
            verdict="not_addressed" when source text is available but tokens
            are absent; verdict="unverifiable" when a citation exists but no
            source text was obtained; verdict="skipped" when neither citation
            nor source text is present.
        """
        if source_text is not None:
            tokens = _salient_tokens(claim_text)
            src_lower = source_text.lower()
            if tokens and all(t in src_lower for t in tokens):
                return Verdict(
                    claim_text=claim_text,
                    citation=citation,
                    verdict="verified",
                    confidence=None,
                    rationale="All salient tokens found in source text.",
                    grader="fetch+heuristic",
                )
            # Either no salient tokens or at least one was absent.
            missing = [t for t in tokens if t not in src_lower]
            snippet = (", ".join(missing[:3]) + ("..." if len(missing) > 3 else ""))
            rationale = (
                ("No salient tokens matched in source." if not tokens
                 else "Token(s) not found in source: " + snippet)
            )[:200]
            return Verdict(
                claim_text=claim_text,
                citation=citation,
                verdict="not_addressed",
                confidence=None,
                rationale=rationale,
                grader="fetch+heuristic",
            )

        if citation is not None:
            return Verdict(
                claim_text=claim_text,
                citation=citation,
                verdict="unverifiable",
                confidence=None,
                rationale="Citation present but source text could not be retrieved.",
                grader="heuristic",
            )

        return Verdict(
            claim_text=claim_text,
            citation=citation,
            verdict="skipped",
            confidence=None,
            rationale="No citation and no source text; nothing to check.",
            grader="heuristic",
        )


# ---------------------------------------------------------------------------
# LLMGrader
# ---------------------------------------------------------------------------

_DEFAULT_MODEL = "claude-haiku-4-5-20251001"
_API_URL = "https://api.anthropic.com/v1/messages"
_VALID_VERDICTS = {"verified", "contradicted", "not_addressed", "unverifiable", "skipped", "error"}

_SYSTEM_PROMPT = (
    "You are a provenance grader. You will be given a factual claim and the "
    "text of a cited source. Assess whether the source text supports, "
    "contradicts, or does not address the claim. "
    "Respond with ONLY a JSON object in this exact format: "
    '{"verdict": "<one of: verified|contradicted|not_addressed|unverifiable|skipped|error>", '
    '"confidence": <float 0.0 to 1.0>, '
    '"rationale": "<explanation under 200 characters>"}'
    " No additional text, no markdown fencing."
)


def _build_user_message(claim_text: str, source_text: Optional[str], citation: Optional[str]) -> str:
    parts = ["Claim: " + claim_text]
    if citation:
        parts.append("Citation: " + citation)
    if source_text:
        # Truncate to avoid very large prompts; 3000 chars is enough context.
        excerpt = source_text[:3000]
        parts.append("Source text (excerpt):\n" + excerpt)
    else:
        parts.append("Source text: (not available)")
    return "\n\n".join(parts)


class LLMGrader:
    """LLM-backed grader using the Anthropic Messages API.

    Requires ANTHROPIC_API_KEY in the environment. Falls back to
    HeuristicGrader on any failure: missing key, network error, non-200
    HTTP response, or JSON parse failure. Never raises.
    """

    def grade(
        self,
        claim_text: str,
        source_text: Optional[str],
        citation: Optional[str],
    ) -> Verdict:
        """Grade a claim, attempting an LLM call first.

        Falls back to HeuristicGrader on any failure. Never raises.
        """
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            return HeuristicGrader().grade(claim_text, source_text, citation)

        model = os.environ.get("PROVENANCE_GRADER_MODEL", _DEFAULT_MODEL)
        grader_label = ("fetch+llm:" + model) if source_text is not None else ("llm:" + model)

        payload = json.dumps({
            "model": model,
            "max_tokens": 256,
            "system": _SYSTEM_PROMPT,
            "messages": [
                {"role": "user", "content": _build_user_message(claim_text, source_text, citation)},
            ],
        }).encode("utf-8")

        req = urllib.request.Request(
            _API_URL,
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                if resp.status != 200:
                    return HeuristicGrader().grade(claim_text, source_text, citation)
                body = resp.read().decode("utf-8", errors="replace")
        except Exception:
            return HeuristicGrader().grade(claim_text, source_text, citation)

        try:
            outer = json.loads(body)
            # The API returns content as a list of blocks.
            raw_text = ""
            content = outer.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        raw_text = block.get("text", "")
                        break
            elif isinstance(content, str):
                raw_text = content
            parsed = json.loads(raw_text)
        except Exception:
            return HeuristicGrader().grade(claim_text, source_text, citation)

        verdict_str = str(parsed.get("verdict", "error"))
        if verdict_str not in _VALID_VERDICTS:
            verdict_str = "error"

        raw_conf = parsed.get("confidence")
        try:
            confidence = float(raw_conf) if raw_conf is not None else None
            if confidence is not None:
                confidence = max(0.0, min(1.0, confidence))
        except (TypeError, ValueError):
            confidence = None

        raw_rationale = str(parsed.get("rationale", ""))[:200]

        return Verdict(
            claim_text=claim_text,
            citation=citation,
            verdict=verdict_str,
            confidence=confidence,
            rationale=raw_rationale,
            grader=grader_label,
        )


# ---------------------------------------------------------------------------
# LocalLLMGrader (OpenAI-compatible endpoint; no Anthropic API key required)
# ---------------------------------------------------------------------------

# Speaks the OpenAI-compatible /v1/chat/completions request shape, which
# Ollama, llama.cpp's server, LM Studio, vLLM, and most local-LLM tools
# implement. Activated by setting PROVENANCE_LOCAL_GRADER_URL; falls
# back to HeuristicGrader on any failure. No data leaves the local
# host.


_LOCAL_DEFAULT_MODEL = "llama3.2"


class LocalLLMGrader:
    """OpenAI-compatible grader for local LLM servers.

    Posts a chat-completions request to ``PROVENANCE_LOCAL_GRADER_URL``
    (e.g. ``http://localhost:11434/v1/chat/completions`` for Ollama).
    Returns a Verdict using the same JSON envelope as ``LLMGrader``.
    Falls back to ``HeuristicGrader`` on any failure: missing env var,
    network error, non-200 response, JSON parse failure.

    Environment variables:

    - ``PROVENANCE_LOCAL_GRADER_URL`` (required to activate): the full
      URL to the chat-completions endpoint.
    - ``PROVENANCE_LOCAL_GRADER_MODEL`` (default ``llama3.2``): model
      name passed in the request body.
    - ``PROVENANCE_LOCAL_GRADER_API_KEY`` (optional): bearer token for
      hosts that require auth (e.g. self-hosted vLLM behind nginx).
      Most local-LLM tools accept no key at all.
    - ``PROVENANCE_LOCAL_GRADER_TIMEOUT`` (default 60s).

    The grader never imports any third-party SDK; the request is built
    with ``urllib.request`` so the stdlib-only guarantee holds.
    """

    def grade(
        self,
        claim_text: str,
        source_text: Optional[str],
        citation: Optional[str],
    ) -> Verdict:
        endpoint = os.environ.get("PROVENANCE_LOCAL_GRADER_URL", "").strip()
        if not endpoint:
            return HeuristicGrader().grade(claim_text, source_text, citation)

        model = os.environ.get("PROVENANCE_LOCAL_GRADER_MODEL", _LOCAL_DEFAULT_MODEL)
        api_key = os.environ.get("PROVENANCE_LOCAL_GRADER_API_KEY", "").strip()
        try:
            timeout = float(os.environ.get("PROVENANCE_LOCAL_GRADER_TIMEOUT", "60"))
        except (TypeError, ValueError):
            timeout = 60.0

        grader_label = (
            "fetch+local-llm:" + model
            if source_text is not None
            else "local-llm:" + model
        )

        payload = json.dumps({
            "model": model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": _build_user_message(claim_text, source_text, citation)},
            ],
            "max_tokens": 256,
            "temperature": 0.0,
            # OpenAI-style response_format request for structured JSON;
            # many local servers honour this, but the grader does not
            # depend on it (the JSON parser handles raw text too).
            "response_format": {"type": "json_object"},
        }).encode("utf-8")

        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = "Bearer " + api_key

        req = urllib.request.Request(endpoint, data=payload, method="POST", headers=headers)

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status != 200:
                    return HeuristicGrader().grade(claim_text, source_text, citation)
                body = resp.read().decode("utf-8", errors="replace")
        except Exception:
            return HeuristicGrader().grade(claim_text, source_text, citation)

        try:
            outer = json.loads(body)
            # OpenAI shape: choices[0].message.content
            choices = outer.get("choices") or []
            if not choices:
                return HeuristicGrader().grade(claim_text, source_text, citation)
            raw_text = choices[0].get("message", {}).get("content", "")
            if not isinstance(raw_text, str):
                raw_text = ""
            # Some local servers wrap the JSON in ```json fences; strip
            # them defensively.
            raw_text = raw_text.strip()
            if raw_text.startswith("```"):
                raw_text = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_text, flags=re.I | re.M)
            parsed = json.loads(raw_text)
        except Exception:
            return HeuristicGrader().grade(claim_text, source_text, citation)

        verdict_str = str(parsed.get("verdict", "error"))
        if verdict_str not in _VALID_VERDICTS:
            verdict_str = "error"

        raw_conf = parsed.get("confidence")
        try:
            confidence = float(raw_conf) if raw_conf is not None else None
            if confidence is not None:
                confidence = max(0.0, min(1.0, confidence))
        except (TypeError, ValueError):
            confidence = None

        raw_rationale = str(parsed.get("rationale", ""))[:200]

        return Verdict(
            claim_text=claim_text,
            citation=citation,
            verdict=verdict_str,
            confidence=confidence,
            rationale=raw_rationale,
            grader=grader_label,
        )


# ---------------------------------------------------------------------------
# CodexGrader
# ---------------------------------------------------------------------------

_CODEX_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": sorted(_VALID_VERDICTS)},
        "confidence": {"type": "number"},
        "rationale": {"type": "string"},
    },
    "required": ["verdict", "confidence", "rationale"],
    "additionalProperties": False,
}


class CodexGrader:
    """Cross-model grader driven by the local Codex CLI (out of band).

    This grader exists for evaluation only. It is never auto-selected by
    get_grader() and is never reachable from the hook. It shells out to
    `codex exec` as a separate, read-only, ephemeral subprocess and feeds it
    exactly the same system prompt, claim, source and citation that
    LLMGrader uses, so the two are a same-task, same-inputs, different-model
    comparison.

    It measures whether a different vendor's model recovers the contradiction
    class that the token-overlap heuristic structurally cannot. Numbers are
    model-dependent and not bit-reproducible. Requires the Codex CLI to be
    installed and authenticated. Degrades to verdict "error" on ANY failure
    (binary missing, non-zero exit, timeout, schema or JSON failure); never
    raises.

    Configuration (environment, all optional):
        PROVENANCE_CODEX_BIN      codex binary name or path (default "codex")
        PROVENANCE_CODEX_TIMEOUT  per-call timeout in seconds (default 120)
        PROVENANCE_CODEX_MODEL    model passed to `codex exec -m` (default:
                                  Codex config default; not overridden)

    Stdlib only: subprocess, tempfile, json, os, re. Python 3.8 compatible.
    """

    grader_label = "codex-cli"

    def _error(self, claim_text, citation, reason):
        return Verdict(
            claim_text=claim_text,
            citation=citation,
            verdict="error",
            confidence=None,
            rationale=str(reason)[:200],
            grader=self.grader_label,
        )

    def grade(
        self,
        claim_text: str,
        source_text: Optional[str],
        citation: Optional[str],
    ) -> Verdict:
        """Grade a claim. Deterministic when there is no source text;
        otherwise delegates the judgement to `codex exec`.
        """
        # No-source path is deterministic and matches HeuristicGrader, so the
        # two graders are compared on identical ground for these items and no
        # Codex call is spent.
        if source_text is None:
            if citation is not None:
                return Verdict(
                    claim_text=claim_text,
                    citation=citation,
                    verdict="unverifiable",
                    confidence=None,
                    rationale="Citation present but source text could not be retrieved.",
                    grader=self.grader_label,
                )
            return Verdict(
                claim_text=claim_text,
                citation=citation,
                verdict="skipped",
                confidence=None,
                rationale="No citation and no source text; nothing to check.",
                grader=self.grader_label,
            )

        import subprocess
        import tempfile

        codex_bin = os.environ.get("PROVENANCE_CODEX_BIN") or self._resolve_codex_bin()
        try:
            timeout = int(os.environ.get("PROVENANCE_CODEX_TIMEOUT", "120"))
        except (TypeError, ValueError):
            timeout = 120
        model = os.environ.get("PROVENANCE_CODEX_MODEL", "")

        prompt = (
            _SYSTEM_PROMPT
            + "\n\n"
            + _build_user_message(claim_text, source_text, citation)
            + "\n\nDo not browse the filesystem or run commands. Answer only "
            "with the JSON object described above."
        )

        schema_path = None
        out_path = None
        try:
            sfd, schema_path = tempfile.mkstemp(suffix=".json", prefix="pv_codex_schema_")
            with os.fdopen(sfd, "w", encoding="utf-8") as fh:
                json.dump(_CODEX_SCHEMA, fh)
            ofd, out_path = tempfile.mkstemp(suffix=".txt", prefix="pv_codex_out_")
            os.close(ofd)

            cmd = [
                codex_bin, "exec",
                "-s", "read-only",
                "--ephemeral",
                "--skip-git-repo-check",
                "--color", "never",
                "--output-schema", schema_path,
                "--output-last-message", out_path,
            ]
            if model:
                cmd += ["-m", model]
            cmd.append("-")  # read the prompt from stdin

            with tempfile.TemporaryDirectory(prefix="pv_codex_cwd_") as workdir:
                try:
                    proc = subprocess.run(
                        cmd,
                        input=prompt,
                        capture_output=True,
                        text=True,
                        timeout=timeout,
                        cwd=workdir,
                    )
                except FileNotFoundError:
                    return self._error(claim_text, citation,
                                       "Codex CLI not found: " + codex_bin)
                except subprocess.TimeoutExpired:
                    return self._error(claim_text, citation,
                                       "Codex call timed out after %ds" % timeout)

                # Check returncode IMMEDIATELY after subprocess returns.
                # Do not attempt to parse output from a failed process.
                if proc.returncode != 0:
                    stderr_msg = (proc.stderr or "").strip()[:120]
                    return self._error(
                        claim_text, citation,
                        "Codex exited %d: %s" % (proc.returncode, stderr_msg))

            try:
                with open(out_path, "r", encoding="utf-8", errors="replace") as fh:
                    raw = fh.read().strip()
            except OSError:
                raw = ""

            if not raw:
                return self._error(claim_text, citation,
                                   "Codex produced no final message.")

            parsed = self._extract_json(raw)
            if parsed is None:
                return self._error(claim_text, citation,
                                   "Could not parse JSON from Codex output.")

            verdict_str = str(parsed.get("verdict", "error"))
            if verdict_str not in _VALID_VERDICTS:
                verdict_str = "error"

            raw_conf = parsed.get("confidence")
            try:
                confidence = float(raw_conf) if raw_conf is not None else None
                if confidence is not None:
                    confidence = max(0.0, min(1.0, confidence))
            except (TypeError, ValueError):
                confidence = None

            rationale = str(parsed.get("rationale", ""))[:200]

            return Verdict(
                claim_text=claim_text,
                citation=citation,
                verdict=verdict_str,
                confidence=confidence,
                rationale=rationale,
                grader=self.grader_label,
            )
        except Exception as exc:  # never raise out of a grader
            return self._error(claim_text, citation, "Codex grader failure: %s" % exc)
        finally:
            for p in (schema_path, out_path):
                if p:
                    try:
                        os.remove(p)
                    except OSError:
                        pass

    @staticmethod
    def _resolve_codex_bin():
        """Resolve the codex executable robustly across platforms.

        On Windows the npm-installed `codex` shim is an extensionless shell
        script that CreateProcess cannot launch, so a bare "codex" fails
        with FileNotFoundError and the grader degrades to verdict "error"
        for every item. The `.cmd` shim runs correctly through subprocess.
        Prefer an extension Windows can execute, then fall back to the bare
        name so behaviour is unchanged on POSIX (where shutil.which for the
        Windows-only names returns None and "codex" resolves normally).
        """
        import shutil
        for name in ("codex.cmd", "codex.exe", "codex"):
            found = shutil.which(name)
            if found:
                return found
        return "codex"

    @staticmethod
    def _extract_json(raw: str):
        """Parse a JSON object from Codex output, tolerating wrapping prose."""
        try:
            return json.loads(raw)
        except Exception:
            pass
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(raw[start:end + 1])
            except Exception:
                return None
        return None


# ---------------------------------------------------------------------------
# ClaudeCliGrader (subscription-over-API: shells out to `claude --print`)
# ---------------------------------------------------------------------------

class ClaudeCliGrader:
    """Grader driven by the local ``claude`` CLI in non-interactive mode.

    This is the subscription-over-API path: it shells out to
    ``claude --print`` (the headless one-shot mode) instead of calling the
    Anthropic Messages API with an ``ANTHROPIC_API_KEY``. It is auto-selected
    by ``get_grader()`` when the ``claude`` binary is on PATH and neither
    ``ANTHROPIC_API_KEY`` nor ``PROVENANCE_LOCAL_GRADER_URL`` is set, so a
    user on a Claude subscription verifies through their plan rather than
    spending API credits.

    It feeds ``claude --print`` exactly the same system prompt, claim, source
    and citation as ``LLMGrader``, so the two are a same-task, same-inputs
    comparison. Degrades to ``HeuristicGrader`` on ANY failure (binary
    missing, non-zero exit, timeout, empty output, JSON parse failure) so the
    grader never raises and never blocks.

    Configuration (environment, all optional):
        PROVENANCE_CLAUDE_BIN      claude binary name or path (default
                                   "claude"; resolved across platforms)
        PROVENANCE_CLAUDE_TIMEOUT  per-call timeout in seconds (default 120)
        PROVENANCE_CLAUDE_MODEL    model passed to `claude --model` (default:
                                   the CLI's configured default; not overridden)

    Stdlib only: subprocess, json, os, re. Python 3.8 compatible.
    """

    def grade(
        self,
        claim_text: str,
        source_text: Optional[str],
        citation: Optional[str],
    ) -> Verdict:
        """Grade a claim via `claude --print`.

        Falls back to HeuristicGrader on any failure. Never raises.
        """
        import subprocess

        claude_bin = os.environ.get("PROVENANCE_CLAUDE_BIN") or self._resolve_claude_bin()
        try:
            timeout = int(os.environ.get("PROVENANCE_CLAUDE_TIMEOUT", "120"))
        except (TypeError, ValueError):
            timeout = 120
        model = os.environ.get("PROVENANCE_CLAUDE_MODEL", "")

        grader_label = (
            "fetch+claude-cli" if source_text is not None else "claude-cli"
        )

        prompt = (
            _SYSTEM_PROMPT
            + "\n\n"
            + _build_user_message(claim_text, source_text, citation)
            + "\n\nAnswer only with the JSON object described above."
        )

        cmd = [claude_bin, "--print"]
        if model:
            cmd += ["--model", model]

        try:
            proc = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except FileNotFoundError:
            return HeuristicGrader().grade(claim_text, source_text, citation)
        except subprocess.TimeoutExpired:
            return HeuristicGrader().grade(claim_text, source_text, citation)
        except Exception:
            return HeuristicGrader().grade(claim_text, source_text, citation)

        if proc.returncode != 0:
            return HeuristicGrader().grade(claim_text, source_text, citation)

        raw = (proc.stdout or "").strip()
        if not raw:
            return HeuristicGrader().grade(claim_text, source_text, citation)

        parsed = CodexGrader._extract_json(raw)
        if parsed is None:
            return HeuristicGrader().grade(claim_text, source_text, citation)

        verdict_str = str(parsed.get("verdict", "error"))
        if verdict_str not in _VALID_VERDICTS:
            verdict_str = "error"

        raw_conf = parsed.get("confidence")
        try:
            confidence = float(raw_conf) if raw_conf is not None else None
            if confidence is not None:
                confidence = max(0.0, min(1.0, confidence))
        except (TypeError, ValueError):
            confidence = None

        rationale = str(parsed.get("rationale", ""))[:200]

        return Verdict(
            claim_text=claim_text,
            citation=citation,
            verdict=verdict_str,
            confidence=confidence,
            rationale=rationale,
            grader=grader_label,
        )

    @staticmethod
    def _resolve_claude_bin():
        """Resolve the claude executable robustly across platforms.

        On Windows the npm-installed `claude` shim is an extensionless shell
        script that CreateProcess cannot launch, so a bare "claude" fails
        with FileNotFoundError. Prefer an extension Windows can execute, then
        fall back to the bare name so behaviour is unchanged on POSIX.
        """
        import shutil
        for name in ("claude.cmd", "claude.exe", "claude"):
            found = shutil.which(name)
            if found:
                return found
        return "claude"

    @staticmethod
    def is_available():
        """Return True if a launchable `claude` binary is on PATH.

        Honours PROVENANCE_CLAUDE_BIN: when set to an explicit path that
        shutil.which resolves, that wins; otherwise the standard shims are
        probed. Used by get_grader() for auto-selection.
        """
        import shutil
        override = os.environ.get("PROVENANCE_CLAUDE_BIN")
        if override:
            return shutil.which(override) is not None
        for name in ("claude.cmd", "claude.exe", "claude"):
            if shutil.which(name):
                return True
        return False


# ---------------------------------------------------------------------------
# Factory functions (named, not lambda, for readable stack traces)
# ---------------------------------------------------------------------------

def _factory_heuristic_grader():
    """Factory: create a HeuristicGrader instance."""
    return HeuristicGrader()


def _factory_local_llm_grader():
    """Factory: create a LocalLLMGrader instance."""
    return LocalLLMGrader()


def _factory_llm_grader():
    """Factory: create an LLMGrader instance."""
    return LLMGrader()


def _factory_claude_cli_grader():
    """Factory: create a ClaudeCliGrader instance."""
    return ClaudeCliGrader()


def _factory_codex_grader():
    """Factory: create a CodexGrader instance."""
    return CodexGrader()


_GRADER_OVERRIDE_REGISTRY = {
    "heuristic": _factory_heuristic_grader,
    "local": _factory_local_llm_grader,
    "local-llm": _factory_local_llm_grader,
    "llm": _factory_llm_grader,
    "anthropic": _factory_llm_grader,
    "claude": _factory_claude_cli_grader,
    "claude-cli": _factory_claude_cli_grader,
    "codex": _factory_codex_grader,
}


def get_grader():
    """Return the most capable grader available in the current environment.

    An explicit ``PROVENANCE_GRADER`` override wins over auto-selection.
    Recognised values (case-insensitive): ``heuristic``, ``local`` /
    ``local-llm``, ``llm`` / ``anthropic``, ``claude`` / ``claude-cli``,
    ``codex``. An unrecognised value is ignored and auto-selection runs.

    Auto-selection order (first match wins):

    1. ``LocalLLMGrader`` if ``PROVENANCE_LOCAL_GRADER_URL`` is set. No
       data egress, no Anthropic API key required. See LocalLLMGrader
       docstring for env vars.
    2. ``LLMGrader`` if ``ANTHROPIC_API_KEY`` is set. Calls the
       Anthropic Messages API.
    3. ``ClaudeCliGrader`` if the ``claude`` CLI is on PATH (and neither
       of the above applies). This is the subscription-over-API path: it
       shells out to ``claude --print`` so a user on a Claude plan verifies
       through their subscription rather than spending API credits.
    4. ``HeuristicGrader`` otherwise. Local, free, deterministic, but
       cannot emit ``contradicted`` by construction.

    ``CodexGrader`` is never auto-selected: it is an evaluation-only
    backend that must be requested explicitly (via ``PROVENANCE_GRADER``
    or the eval harness).

    Order rationale: an explicit API key or local-LLM URL signals a
    deliberate choice and is honoured first. The ``claude`` CLI is the
    subscription-over-API fallback (no credits spent) when no key is set.
    The heuristic is the final fallback.
    """
    override = (os.environ.get("PROVENANCE_GRADER") or "").strip().lower()
    if override in _GRADER_OVERRIDE_REGISTRY:
        return _GRADER_OVERRIDE_REGISTRY[override]()

    if os.environ.get("PROVENANCE_LOCAL_GRADER_URL"):
        return LocalLLMGrader()
    if os.environ.get("ANTHROPIC_API_KEY"):
        return LLMGrader()
    if ClaudeCliGrader.is_available():
        return ClaudeCliGrader()
    return HeuristicGrader()
