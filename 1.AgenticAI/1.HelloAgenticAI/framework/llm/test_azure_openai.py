"""Unit tests for the Azure OpenAI client wrapper.

Tests inject a mocked AsyncAzureOpenAI so they never touch the network.
The integration suite exercises the real AOAI deployment end-to-end.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel

from framework.llm.azure_openai import AzureOpenAIClient

# ---------- helpers ----------


def _make_chat_response(content: str | None) -> Any:
    """Shape that mimics openai.types.chat.ChatCompletion."""
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def _make_parse_response(parsed: BaseModel | None) -> Any:
    msg = MagicMock()
    msg.parsed = parsed
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def _make_embed_response(vectors: list[list[float]]) -> Any:
    """Shape that mimics openai.types.CreateEmbeddingResponse."""
    resp = MagicMock()
    resp.data = [MagicMock(embedding=v) for v in vectors]
    return resp


def _mock_aoai() -> MagicMock:
    """Mock AsyncAzureOpenAI with the surface our wrapper uses."""
    client = MagicMock()
    client.chat.completions.create = AsyncMock()
    client.chat.completions.parse = AsyncMock()
    client.embeddings.create = AsyncMock()
    client.close = AsyncMock()
    return client


@pytest.fixture
def mock_client() -> MagicMock:
    return _mock_aoai()


@pytest.fixture
def wrapper(mock_client: MagicMock) -> AzureOpenAIClient:
    return AzureOpenAIClient(client=mock_client)


# ---------- properties / construction ----------


def test_default_deployments_match_phase_1_bicep(wrapper: AzureOpenAIClient) -> None:
    """Bicep AOAI module deploys these three names — wrapper defaults align."""
    assert wrapper.chat_large_deployment == "gpt-4o"
    assert wrapper.chat_mini_deployment == "gpt-4o-mini"
    assert wrapper.embeddings_deployment == "text-embedding-3-large"


def test_custom_deployments_override_defaults(mock_client: MagicMock) -> None:
    w = AzureOpenAIClient(
        client=mock_client,
        chat_large_deployment="custom-large",
        chat_mini_deployment="custom-mini",
        embeddings_deployment="custom-embed",
    )
    assert w.chat_large_deployment == "custom-large"
    assert w.chat_mini_deployment == "custom-mini"
    assert w.embeddings_deployment == "custom-embed"


# ---------- chat ----------


async def test_chat_returns_message_content(
    wrapper: AzureOpenAIClient, mock_client: MagicMock
) -> None:
    mock_client.chat.completions.create.return_value = _make_chat_response("hello")
    out = await wrapper.chat([{"role": "user", "content": "hi"}])
    assert out == "hello"


async def test_chat_uses_chat_large_deployment_by_default(
    wrapper: AzureOpenAIClient, mock_client: MagicMock
) -> None:
    mock_client.chat.completions.create.return_value = _make_chat_response("ok")
    await wrapper.chat([{"role": "user", "content": "hi"}])
    args = mock_client.chat.completions.create.await_args
    assert args.kwargs["model"] == "gpt-4o"


async def test_chat_uses_explicit_deployment_when_given(
    wrapper: AzureOpenAIClient, mock_client: MagicMock
) -> None:
    mock_client.chat.completions.create.return_value = _make_chat_response("ok")
    await wrapper.chat(
        [{"role": "user", "content": "hi"}],
        deployment="gpt-4o-mini",
    )
    args = mock_client.chat.completions.create.await_args
    assert args.kwargs["model"] == "gpt-4o-mini"


async def test_chat_passes_temperature_and_max_tokens(
    wrapper: AzureOpenAIClient, mock_client: MagicMock
) -> None:
    mock_client.chat.completions.create.return_value = _make_chat_response("ok")
    await wrapper.chat(
        [{"role": "user", "content": "hi"}],
        temperature=0.7,
        max_tokens=128,
    )
    args = mock_client.chat.completions.create.await_args
    assert args.kwargs["temperature"] == 0.7
    assert args.kwargs["max_tokens"] == 128


async def test_chat_raises_on_empty_content(
    wrapper: AzureOpenAIClient, mock_client: MagicMock
) -> None:
    mock_client.chat.completions.create.return_value = _make_chat_response(None)
    with pytest.raises(RuntimeError, match="no content"):
        await wrapper.chat([{"role": "user", "content": "hi"}])


# ---------- chat_structured ----------


class _Plan(BaseModel):
    goal: str
    steps: list[str]


async def test_chat_structured_returns_parsed_model(
    wrapper: AzureOpenAIClient, mock_client: MagicMock
) -> None:
    plan = _Plan(goal="g", steps=["a", "b"])
    mock_client.chat.completions.parse.return_value = _make_parse_response(plan)
    out = await wrapper.chat_structured(
        [{"role": "user", "content": "plan it"}],
        response_model=_Plan,
    )
    assert out == plan


async def test_chat_structured_passes_response_model_to_sdk(
    wrapper: AzureOpenAIClient, mock_client: MagicMock
) -> None:
    plan = _Plan(goal="g", steps=["a"])
    mock_client.chat.completions.parse.return_value = _make_parse_response(plan)
    await wrapper.chat_structured(
        [{"role": "user", "content": "plan"}],
        response_model=_Plan,
    )
    args = mock_client.chat.completions.parse.await_args
    assert args.kwargs["response_format"] is _Plan


async def test_chat_structured_retries_on_none_then_succeeds(
    wrapper: AzureOpenAIClient, mock_client: MagicMock
) -> None:
    plan = _Plan(goal="g", steps=["a"])
    # first call returns None (empty parsed), second returns the plan
    mock_client.chat.completions.parse.side_effect = [
        _make_parse_response(None),
        _make_parse_response(plan),
    ]
    out = await wrapper.chat_structured(
        [{"role": "user", "content": "plan"}],
        response_model=_Plan,
        max_retries=1,
    )
    assert out == plan
    assert mock_client.chat.completions.parse.await_count == 2


async def test_chat_structured_raises_after_retries_exhausted(
    wrapper: AzureOpenAIClient, mock_client: MagicMock
) -> None:
    mock_client.chat.completions.parse.return_value = _make_parse_response(None)
    with pytest.raises(RuntimeError, match="parsed=None"):
        await wrapper.chat_structured(
            [{"role": "user", "content": "plan"}],
            response_model=_Plan,
            max_retries=2,
        )
    # initial + 2 retries = 3 total calls
    assert mock_client.chat.completions.parse.await_count == 3


# ---------- embeddings ----------


async def test_embed_single_string_returns_one_vector(
    wrapper: AzureOpenAIClient, mock_client: MagicMock
) -> None:
    vec = [0.1, 0.2, 0.3]
    mock_client.embeddings.create.return_value = _make_embed_response([vec])
    out = await wrapper.embed("hello")
    assert out == [vec]
    args = mock_client.embeddings.create.await_args
    assert args.kwargs["input"] == ["hello"]
    assert args.kwargs["model"] == "text-embedding-3-large"


async def test_embed_list_returns_many_vectors(
    wrapper: AzureOpenAIClient, mock_client: MagicMock
) -> None:
    vecs = [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]]
    mock_client.embeddings.create.return_value = _make_embed_response(vecs)
    out = await wrapper.embed(["a", "b", "c"])
    assert out == vecs


# ---------- lifecycle ----------


async def test_close_calls_underlying_close(
    wrapper: AzureOpenAIClient, mock_client: MagicMock
) -> None:
    await wrapper.close()
    mock_client.close.assert_awaited_once()


async def test_async_context_manager(mock_client: MagicMock) -> None:
    wrapper = AzureOpenAIClient(client=mock_client)
    async with wrapper as w:
        assert w is wrapper
    mock_client.close.assert_awaited_once()
