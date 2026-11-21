"""Tests for retry logic in the BoltzmannClient (ported from requests to httpx, matching client.py)."""

import pytest
from unittest.mock import patch, MagicMock
import httpx

from tcadai_cli.client import BoltzmannClient, APIError


def _mock_response(status_code, json_data=None, text=""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.json.return_value = json_data or {}
    return resp


class TestRetryLogic:
    def setup_method(self):
        self.client = BoltzmannClient("http://localhost:8009", api_key="k")

    @patch("tcadai_cli.client.time.sleep")
    @patch("tcadai_cli.client.httpx.request")
    def test_retries_on_429(self, mock_request, mock_sleep):
        mock_request.side_effect = [_mock_response(429), _mock_response(200, {"ok": True})]
        result = self.client.get("/test")
        assert result == {"ok": True}
        assert mock_request.call_count == 2
        mock_sleep.assert_called_once()

    @patch("tcadai_cli.client.time.sleep")
    @patch("tcadai_cli.client.httpx.request")
    def test_retries_on_502(self, mock_request, mock_sleep):
        resp_502 = _mock_response(502, text="Bad Gateway")
        resp_502.json.side_effect = Exception("not json")
        mock_request.side_effect = [resp_502, _mock_response(200, {"ok": True})]
        assert self.client.get("/test") == {"ok": True}

    @patch("tcadai_cli.client.time.sleep")
    @patch("tcadai_cli.client.httpx.request")
    def test_does_not_retry_on_400(self, mock_request, mock_sleep):
        mock_request.return_value = _mock_response(400, {"detail": "bad request"})
        with pytest.raises(APIError, match="400"):
            self.client.get("/test")
        assert mock_request.call_count == 1
        mock_sleep.assert_not_called()

    @patch("tcadai_cli.client.MAX_RETRIES", 2)
    @patch("tcadai_cli.client.time.sleep")
    @patch("tcadai_cli.client.httpx.request")
    def test_gives_up_after_max_retries(self, mock_request, mock_sleep):
        mock_request.return_value = _mock_response(500, {"detail": "server error"})
        with pytest.raises(APIError, match="500"):
            self.client.get("/test")
        assert mock_request.call_count == 3  # MAX_RETRIES + 1

    @patch("tcadai_cli.client.time.sleep")
    @patch("tcadai_cli.client.httpx.request")
    def test_retries_on_connection_error(self, mock_request, mock_sleep):
        mock_request.side_effect = [
            httpx.ConnectError("refused"),
            _mock_response(200, {"ok": True}),
        ]
        assert self.client.get("/test") == {"ok": True}
        mock_sleep.assert_called_once()

    @patch("tcadai_cli.client.MAX_RETRIES", 0)
    @patch("tcadai_cli.client.time.sleep")
    @patch("tcadai_cli.client.httpx.request")
    def test_connection_error_after_max_retries_raises(self, mock_request, mock_sleep):
        mock_request.side_effect = httpx.ConnectError("refused")
        with pytest.raises(APIError, match="Connection failed"):
            self.client.get("/test")

    @patch("tcadai_cli.client.MAX_RETRIES", 0)
    @patch("tcadai_cli.client.httpx.request")
    def test_no_retries_when_disabled(self, mock_request):
        mock_request.return_value = _mock_response(500, {"detail": "error"})
        with pytest.raises(APIError):
            self.client.get("/test")
        assert mock_request.call_count == 1


class TestNonIdempotentRetry:
    """P-BZ-027 / K-031: POST/PATCH are not replayed on 5xx or mid-flight errors."""

    def setup_method(self):
        self.client = BoltzmannClient("http://localhost:8009", api_key="k")

    @patch("tcadai_cli.client.time.sleep")
    @patch("tcadai_cli.client.httpx.request")
    @pytest.mark.parametrize("verb", ["post", "patch"])
    def test_no_retry_on_5xx(self, mock_request, mock_sleep, verb):
        mock_request.return_value = _mock_response(503, {"detail": "down"})
        with pytest.raises(APIError, match="503"):
            getattr(self.client, verb)("/x", {"a": 1})
        assert mock_request.call_count == 1

    @patch("tcadai_cli.client.time.sleep")
    @patch("tcadai_cli.client.httpx.request")
    def test_post_retries_429(self, mock_request, mock_sleep):
        mock_request.side_effect = [_mock_response(429), _mock_response(200, {"ok": True})]
        assert self.client.post("/x", {"a": 1}) == {"ok": True}
        assert mock_request.call_count == 2

    @patch("tcadai_cli.client.time.sleep")
    @patch("tcadai_cli.client.httpx.request")
    def test_post_no_retry_on_read_timeout(self, mock_request, mock_sleep):
        mock_request.side_effect = httpx.ReadTimeout("slow")
        with pytest.raises(APIError, match="Connection failed"):
            self.client.post("/x", {"a": 1})
        assert mock_request.call_count == 1

    @patch("tcadai_cli.client.time.sleep")
    @patch("tcadai_cli.client.httpx.request")
    def test_post_retries_connect_error(self, mock_request, mock_sleep):
        mock_request.side_effect = [httpx.ConnectError("refused"), _mock_response(200, {"ok": 1})]
        assert self.client.post("/x", {}) == {"ok": 1}

    @patch("tcadai_cli.client.time.sleep")
    @patch("tcadai_cli.client.httpx.request")
    def test_get_still_retries_5xx(self, mock_request, mock_sleep):
        mock_request.side_effect = [_mock_response(503), _mock_response(200, {"ok": 1})]
        assert self.client.get("/x") == {"ok": 1}
