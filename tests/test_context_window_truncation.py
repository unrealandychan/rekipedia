import pytest
from unittest.mock import patch, MagicMock


def test_call_truncates_on_context_window_exceeded():
    """LLMClient.call() should retry with truncated prompt on ContextWindowExceededError."""
    from rekipedia.llm.client import LLMClient
    from rekipedia.models.contracts import LLMConfig
    import litellm

    client = LLMClient(LLMConfig(model="gpt-4o", api_key="test"))
    call_count = 0

    def mock_completion(**kwargs):
        nonlocal call_count
        call_count += 1
        user_msg = next(m["content"] for m in kwargs["messages"] if m["role"] == "user")
        if len(user_msg) > 100:  # first call with long prompt
            raise litellm.ContextWindowExceededError(
                message="token limit exceeded", model="gpt-4o", llm_provider="openai"
            )
        # second call with truncated prompt succeeds
        resp = MagicMock()
        resp.choices[0].message.content = "ok"
        resp.usage = None
        return resp

    with patch("litellm.completion", side_effect=mock_completion):
        result = client.call("x" * 130)  # 130 * 0.75 = 97 chars after truncation, which is ≤ 100
    assert result == "ok"
    assert call_count == 2  # failed once, succeeded once after truncation


def test_call_raises_after_max_truncation_attempts():
    """LLMClient.call() should raise after exhausting truncation retries."""
    from rekipedia.llm.client import LLMClient
    from rekipedia.models.contracts import LLMConfig
    import litellm

    client = LLMClient(LLMConfig(model="gpt-4o", api_key="test"))

    def always_exceed(**kwargs):
        raise litellm.ContextWindowExceededError(
            message="token limit exceeded", model="gpt-4o", llm_provider="openai"
        )

    with patch("litellm.completion", side_effect=always_exceed):
        with pytest.raises(litellm.ContextWindowExceededError):
            client.call("x" * 1000)
