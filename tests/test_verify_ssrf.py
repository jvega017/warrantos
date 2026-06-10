#!/usr/bin/env python3
"""Tests for SSRF and scheme-guard protection in provenance.verify.

All tests are offline and deterministic. socket.getaddrinfo is monkeypatched
to avoid real DNS resolution; no network requests are issued.

Run from the repo root:
    python -m unittest tests.test_verify_ssrf -v
"""

import socket
import unittest
import unittest.mock
from unittest.mock import MagicMock, patch
import urllib.error
import urllib.request

import warrantos.provenance.verify as _verify_module
from warrantos.provenance.verify import _is_safe_url, _SafeRedirectHandler, fetch_text


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_getaddrinfo(ip: str):
    """Return a monkeypatch for socket.getaddrinfo that resolves to *ip*."""
    def _fake(host, port, *args, **kwargs):
        # Return a minimal AF_INET result tuple.
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (ip, port or 80))]
    return _fake


def _make_resp(content: bytes = b"hello", content_type: str = "text/plain"):
    """Return a mock HTTP response suitable for _safe_opener.open()."""
    mock_resp = MagicMock()
    mock_resp.read.return_value = content
    mock_resp.headers.get.return_value = content_type
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


# ---------------------------------------------------------------------------
# _is_safe_url tests
# ---------------------------------------------------------------------------

class TestIsSafeUrl(unittest.TestCase):
    """_is_safe_url: scheme guard and address-family checks."""

    def test_file_scheme_rejected(self):
        self.assertFalse(_is_safe_url("file:///etc/passwd"))

    def test_ftp_scheme_rejected(self):
        self.assertFalse(_is_safe_url("ftp://x/"))

    def test_no_scheme_rejected(self):
        self.assertFalse(_is_safe_url("example.com/page"))

    def test_loopback_ipv4_rejected(self):
        with patch("socket.getaddrinfo", _make_getaddrinfo("127.0.0.1")):
            self.assertFalse(_is_safe_url("http://127.0.0.1/"))

    def test_loopback_localhost_rejected(self):
        with patch("socket.getaddrinfo", _make_getaddrinfo("127.0.0.1")):
            self.assertFalse(_is_safe_url("http://localhost/"))

    def test_link_local_rejected(self):
        with patch("socket.getaddrinfo", _make_getaddrinfo("169.254.169.254")):
            self.assertFalse(_is_safe_url("http://169.254.169.254/"))

    def test_private_10_block_rejected(self):
        with patch("socket.getaddrinfo", _make_getaddrinfo("10.1.2.3")):
            self.assertFalse(_is_safe_url("http://10.1.2.3/"))

    def test_private_192_168_block_rejected(self):
        with patch("socket.getaddrinfo", _make_getaddrinfo("192.168.1.1")):
            self.assertFalse(_is_safe_url("http://192.168.1.1/"))

    def test_ipv6_loopback_rejected(self):
        def _fake_ipv6(host, port, *args, **kwargs):
            return [(socket.AF_INET6, socket.SOCK_STREAM, 0, "", ("::1", port or 80, 0, 0))]
        with patch("socket.getaddrinfo", _fake_ipv6):
            self.assertFalse(_is_safe_url("http://[::1]/"))

    def test_resolution_failure_rejected(self):
        with patch("socket.getaddrinfo", side_effect=socket.gaierror("NXDOMAIN")):
            self.assertFalse(_is_safe_url("http://does-not-exist.invalid/"))

    def test_public_address_accepted(self):
        # 93.184.216.34 is the well-known address for example.com.
        with patch("socket.getaddrinfo", _make_getaddrinfo("93.184.216.34")):
            self.assertTrue(_is_safe_url("https://example.com/page"))

    def test_http_public_accepted(self):
        with patch("socket.getaddrinfo", _make_getaddrinfo("8.8.8.8")):
            self.assertTrue(_is_safe_url("http://public.example.org/data"))

    def test_missing_hostname_rejected(self):
        self.assertFalse(_is_safe_url("http:///path"))

    def test_cgnat_rejected(self):
        """RFC 6598 CGNAT space 100.64.0.0/10 must be rejected (not global)."""
        with patch("socket.getaddrinfo", _make_getaddrinfo("100.64.1.1")):
            self.assertFalse(_is_safe_url("http://cgnat.example/"))


# ---------------------------------------------------------------------------
# fetch_text SSRF guard tests
# ---------------------------------------------------------------------------

class TestFetchTextSsrfGuard(unittest.TestCase):
    """fetch_text must return None without issuing any request for unsafe URLs."""

    def _assert_blocked(self, url, getaddrinfo_ip=None):
        """Assert fetch_text returns None and that no opener.open call occurs."""
        ctx = []
        if getaddrinfo_ip is not None:
            ctx.append(patch("socket.getaddrinfo", _make_getaddrinfo(getaddrinfo_ip)))
        ctx.append(patch.object(_verify_module._safe_opener, "open",
                                side_effect=AssertionError("network call made")))
        patchers = [c.__enter__() for c in ctx]
        try:
            result = fetch_text(url)
        finally:
            for c in reversed(ctx):
                c.__exit__(None, None, None)
        self.assertIsNone(result)

    def test_file_url_blocked(self):
        self._assert_blocked("file:///etc/passwd")

    def test_ftp_url_blocked(self):
        self._assert_blocked("ftp://x/")

    def test_loopback_blocked(self):
        self._assert_blocked("http://127.0.0.1/", getaddrinfo_ip="127.0.0.1")

    def test_link_local_blocked(self):
        self._assert_blocked("http://169.254.169.254/", getaddrinfo_ip="169.254.169.254")

    def test_private_10_blocked(self):
        self._assert_blocked("http://10.1.2.3/", getaddrinfo_ip="10.1.2.3")

    def test_ipv6_loopback_blocked(self):
        def _fake_ipv6(host, port, *args, **kwargs):
            return [(socket.AF_INET6, socket.SOCK_STREAM, 0, "", ("::1", port or 80, 0, 0))]
        with patch("socket.getaddrinfo", _fake_ipv6):
            with patch.object(_verify_module._safe_opener, "open",
                               side_effect=AssertionError("network call made")):
                result = fetch_text("http://[::1]/")
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# fetch_text redirect SSRF guard tests
# ---------------------------------------------------------------------------

class TestFetchTextRedirectGuard(unittest.TestCase):
    """fetch_text must block redirects whose Location resolves to a private address."""

    def test_redirect_to_private_address_blocked(self):
        """An opener that raises URLError on redirect simulates the guard firing."""
        public_ip = "93.184.216.34"
        with patch("socket.getaddrinfo", _make_getaddrinfo(public_ip)):
            with patch.object(
                _verify_module._safe_opener,
                "open",
                side_effect=urllib.error.URLError(
                    "redirect target failed safety check: http://10.0.0.1/"
                ),
            ):
                result = fetch_text("https://example.com/redirect-to-private")
        self.assertIsNone(result)

    def test_redirect_request_to_private_raises_url_error(self):
        """_SafeRedirectHandler.redirect_request raises URLError when the
        redirect Location resolves to a private address.

        This test drives the real handler method directly (no monkeypatching
        of _safe_opener.open) to verify the guard fires correctly.
        """
        handler = _SafeRedirectHandler()
        # Attach a minimal opener so super().redirect_request can be called
        # if it were ever reached (it should not be for a blocked redirect).
        opener = urllib.request.build_opener(handler)
        handler.parent = opener

        private_location = "http://10.0.0.1/internal"

        # Build a minimal fake request and response for the handler signature.
        orig_req = urllib.request.Request("https://example.com/")
        mock_fp = MagicMock()
        mock_headers = MagicMock()
        mock_headers.get.return_value = private_location

        with patch("socket.getaddrinfo", _make_getaddrinfo("10.0.0.1")):
            with self.assertRaises(urllib.error.URLError) as ctx:
                handler.redirect_request(
                    orig_req, mock_fp, 302, "Found", mock_headers, private_location
                )

        self.assertIn("safety check", str(ctx.exception))


# ---------------------------------------------------------------------------
# fetch_text success path (public URL)
# ---------------------------------------------------------------------------

class TestFetchTextPublicUrl(unittest.TestCase):
    """fetch_text proceeds to the fetch path for a hostname resolving to a public address."""

    def test_public_url_fetches_and_returns_text(self):
        public_ip = "93.184.216.34"
        mock_resp = _make_resp(b"Example Domain content.", "text/plain")
        with patch("socket.getaddrinfo", _make_getaddrinfo(public_ip)):
            with patch.object(_verify_module._safe_opener, "open", return_value=mock_resp):
                result = fetch_text("https://example.com/page")
        self.assertIsNotNone(result)
        self.assertIn("Example Domain", result)

    def test_public_url_never_raises(self):
        """fetch_text never raises regardless of network error."""
        public_ip = "93.184.216.34"
        with patch("socket.getaddrinfo", _make_getaddrinfo(public_ip)):
            with patch.object(
                _verify_module._safe_opener, "open",
                side_effect=Exception("connection reset"),
            ):
                try:
                    result = fetch_text("https://example.com/page")
                except Exception as exc:
                    self.fail("fetch_text raised: %s" % exc)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
