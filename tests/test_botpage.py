import logging
import socket
import pytest
import botpage
from botpage import (
    _get_text_content,
    _is_safe_url,
    handle_function_call,
    prepare_messages_for_api,
    process_tool_calls,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _session(messages):
    return {"messages": messages}


# ---------------------------------------------------------------------------
# _is_safe_url
# ---------------------------------------------------------------------------


class TestIsSafeUrl:
    def test_non_http_scheme_blocked(self):
        assert _is_safe_url("ftp://example.com") is False

    def test_empty_url_blocked(self):
        assert _is_safe_url("") is False

    def test_private_ip_blocked(self):
        assert _is_safe_url("http://192.168.1.1/admin") is False

    def test_loopback_blocked(self):
        assert _is_safe_url("http://127.0.0.1") is False

    def test_link_local_blocked(self):
        assert _is_safe_url("http://169.254.169.254/latest/meta-data/") is False

    def test_public_ip_allowed(self, monkeypatch):
        monkeypatch.setattr(socket, "gethostbyname", lambda h: "93.184.216.34")
        assert _is_safe_url("https://example.com") is True

    def test_internal_hostname_resolving_to_private_ip_blocked(self, monkeypatch):
        monkeypatch.setattr(socket, "gethostbyname", lambda h: "10.0.0.1")
        assert _is_safe_url("https://internal.corp") is False

    def test_dns_failure_blocked(self, monkeypatch):
        def _raise(h):
            raise socket.gaierror("dns failure")

        monkeypatch.setattr(socket, "gethostbyname", _raise)
        assert _is_safe_url("https://nonexistent.invalid") is False


# ---------------------------------------------------------------------------
# prepare_messages_for_api
# ---------------------------------------------------------------------------


class TestPrepareMessagesForApi:
    def test_empty_session_returns_empty_list(self):
        assert prepare_messages_for_api(_session([])) == []

    def test_simple_messages_returned_in_order(self):
        msgs = [
            {"role": "user", "content": "hello", "reasoning_content": ""},
            {"role": "assistant", "content": "hi", "reasoning_content": ""},
        ]
        result = prepare_messages_for_api(_session(msgs))
        assert len(result) == 2
        assert result[0] == {"role": "user", "content": "hello"}
        assert result[1] == {"role": "assistant", "content": "hi"}

    def test_truncation_discards_older_messages(self):
        msgs = [
            {"role": "user", "content": "old", "reasoning_content": ""},
            {"role": "assistant", "content": "old reply", "reasoning_content": ""},
            {"role": "truncation", "content": "", "reasoning_content": ""},
            {"role": "user", "content": "new", "reasoning_content": ""},
            {"role": "assistant", "content": "new reply", "reasoning_content": ""},
        ]
        result = prepare_messages_for_api(_session(msgs))
        assert len(result) == 2
        assert result[0]["content"] == "<user_input>new</user_input>"
        assert result[1]["content"] == "new reply"

    def test_truncation_wraps_first_user_message(self):
        msgs = [
            {"role": "user", "content": "old", "reasoning_content": ""},
            {"role": "truncation", "content": "", "reasoning_content": ""},
            {"role": "user", "content": "new", "reasoning_content": ""},
        ]
        result = prepare_messages_for_api(_session(msgs))
        assert len(result) == 1
        assert result[0]["content"] == "<user_input>new</user_input>"

    def test_tool_calls_field_preserved(self):
        tool_calls = [
            {
                "id": "t1",
                "type": "function",
                "function": {
                    "name": "fetch_url",
                    "arguments": '{"url":"https://x.com"}',
                },
            }
        ]
        msgs = [
            {
                "role": "assistant",
                "content": "",
                "reasoning_content": "",
                "tool_calls": tool_calls,
            }
        ]
        result = prepare_messages_for_api(_session(msgs))
        assert result[0]["tool_calls"] == tool_calls

    def test_tool_call_id_field_preserved(self):
        msgs = [
            {
                "role": "tool",
                "content": "result",
                "reasoning_content": "",
                "tool_call_id": "t1",
            }
        ]
        result = prepare_messages_for_api(_session(msgs))
        assert result[0]["tool_call_id"] == "t1"

    def test_reasoning_content_not_sent_to_api(self):
        msgs = [
            {
                "role": "assistant",
                "content": "answer",
                "reasoning_content": "thinking...",
            }
        ]
        result = prepare_messages_for_api(_session(msgs))
        assert "reasoning_content" not in result[0]

    def test_multiple_truncations_uses_last_one(self):
        msgs = [
            {"role": "user", "content": "very old", "reasoning_content": ""},
            {"role": "truncation", "content": "", "reasoning_content": ""},
            {"role": "user", "content": "old", "reasoning_content": ""},
            {"role": "truncation", "content": "", "reasoning_content": ""},
            {"role": "user", "content": "current", "reasoning_content": ""},
        ]
        result = prepare_messages_for_api(_session(msgs))
        assert len(result) == 1
        assert result[0]["content"] == "<user_input>current</user_input>"


# ---------------------------------------------------------------------------
# _get_text_content
# ---------------------------------------------------------------------------


class TestGetTextContent:
    def test_string_returns_as_is(self):
        assert _get_text_content("hello") == "hello"

    def test_list_with_text_parts_joins(self):
        content = [
            {"type": "text", "text": "hello"},
            {"type": "text", "text": "world"},
        ]
        assert _get_text_content(content) == "hello\nworld"

    def test_list_mixed_types_extracts_text_only(self):
        content = [
            {"type": "text", "text": "hello"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
        ]
        assert _get_text_content(content) == "hello"

    def test_empty_list_returns_empty(self):
        assert _get_text_content([]) == ""

    def test_list_without_text_parts_returns_empty(self):
        content = [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}}
        ]
        assert _get_text_content(content) == ""

    def test_unexpected_type_returns_empty_and_logs_warning(self, caplog):
        caplog.set_level(logging.WARNING)
        result = _get_text_content(42)
        assert result == ""
        assert "Unexpected content type" in caplog.text
        assert "int" in caplog.text


# ---------------------------------------------------------------------------
# handle_function_call
# ---------------------------------------------------------------------------


class TestHandleFunctionCall:
    def test_unknown_function_returns_error(self):
        result = handle_function_call("nonexistent", {})
        assert "error" in result

    def test_fetch_url_missing_url_param_returns_error(self):
        result = handle_function_call("fetch_url", {})
        assert "error" in result

    def test_fetch_url_success(self, monkeypatch):
        monkeypatch.setattr(botpage, "fetch_url", lambda url: "# Content")
        result = handle_function_call("fetch_url", {"url": "https://example.com"})
        assert result == {"content": "# Content"}

    def test_fetch_url_returns_error_when_fetch_fails(self, monkeypatch):
        monkeypatch.setattr(botpage, "fetch_url", lambda url: None)
        result = handle_function_call("fetch_url", {"url": "https://example.com"})
        assert "error" in result

    def test_exception_inside_handler_returns_error(self, monkeypatch):
        def _boom(url):
            raise RuntimeError("unexpected")

        monkeypatch.setattr(botpage, "fetch_url", _boom)
        result = handle_function_call("fetch_url", {"url": "https://example.com"})
        assert "error" in result
