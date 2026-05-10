"""Typed async wrapper around Azure OpenAI with AAD-only authentication.

No API keys anywhere — bearer token via the user-assigned managed identity
in production, ``az login`` locally. Three operations exposed:

* :meth:`AzureOpenAIClient.chat` — plain text completion
* :meth:`AzureOpenAIClient.chat_structured` — Pydantic-validated structured
  output with retry-on-None
* :meth:`AzureOpenAIClient.embed` — single or batch embeddings

The wrapper is intentionally thin — it does not emit observability events
(the agent layer does that, keeping LLM logic pure). Phase 4 may add
:class:`AgentEventType.LLM_CALL_START` / ``LLM_CALL_COMPLETE`` here.

Constructor takes a pre-built :class:`AsyncAzureOpenAI` for testability
(unit tests inject a mock); the :meth:`from_endpoint` classmethod is the
production-side factory that wires :class:`DefaultAzureCredential`.
"""

from __future__ import annotations

from collections.abc import Sequence
from types import TracebackType
from typing import TypeVar

from openai import AsyncAzureOpenAI
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class AzureOpenAIClient:
    """Async Azure OpenAI client wrapper with typed methods."""

    DEFAULT_API_VERSION = "2024-10-21"
    SCOPE = "https://cognitiveservices.azure.com/.default"

    def __init__(
        self,
        *,
        client: AsyncAzureOpenAI,
        chat_large_deployment: str = "gpt-4o",
        chat_mini_deployment: str = "gpt-4o-mini",
        embeddings_deployment: str = "text-embedding-3-large",
    ) -> None:
        self._client = client
        self._chat_large_deployment = chat_large_deployment
        self._chat_mini_deployment = chat_mini_deployment
        self._embeddings_deployment = embeddings_deployment

    # ----- factories -----

    @classmethod
    def from_endpoint(
        cls,
        *,
        endpoint: str,
        chat_large_deployment: str = "gpt-4o",
        chat_mini_deployment: str = "gpt-4o-mini",
        embeddings_deployment: str = "text-embedding-3-large",
        api_version: str = DEFAULT_API_VERSION,
    ) -> AzureOpenAIClient:
        """Production factory — wires DefaultAzureCredential to the SDK.

        Imports are local so unit tests that mock the SDK don't pay the
        azure-identity import cost.
        """
        from azure.identity.aio import (
            DefaultAzureCredential,
            get_bearer_token_provider,
        )

        credential = DefaultAzureCredential()
        token_provider = get_bearer_token_provider(credential, cls.SCOPE)
        client = AsyncAzureOpenAI(
            azure_endpoint=endpoint,
            azure_ad_token_provider=token_provider,
            api_version=api_version,
        )
        return cls(
            client=client,
            chat_large_deployment=chat_large_deployment,
            chat_mini_deployment=chat_mini_deployment,
            embeddings_deployment=embeddings_deployment,
        )

    # ----- properties -----

    @property
    def chat_large_deployment(self) -> str:
        return self._chat_large_deployment

    @property
    def chat_mini_deployment(self) -> str:
        return self._chat_mini_deployment

    @property
    def embeddings_deployment(self) -> str:
        return self._embeddings_deployment

    # ----- operations -----

    async def chat(
        self,
        messages: Sequence[ChatCompletionMessageParam],
        *,
        deployment: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> str:
        """Plain text chat completion — returns the assistant's content."""
        resp = await self._client.chat.completions.create(
            model=deployment or self._chat_large_deployment,
            messages=list(messages),
            temperature=temperature,
            max_tokens=max_tokens,
        )
        content = resp.choices[0].message.content
        if content is None:
            raise RuntimeError("AOAI returned a chat response with no content")
        return content

    async def chat_structured(
        self,
        messages: Sequence[ChatCompletionMessageParam],
        *,
        response_model: type[T],
        deployment: str | None = None,
        temperature: float = 0.0,
        max_retries: int = 1,
    ) -> T:
        """Chat completion with Pydantic-validated structured output.

        Uses OpenAI's structured-outputs (``response_format=<Model>``) API.
        Retries up to ``max_retries`` extra times if the model returns
        ``parsed=None`` (rare but possible for ambiguous schemas).
        """
        last_error: Exception | None = None
        for _attempt in range(max_retries + 1):
            resp = await self._client.chat.completions.parse(
                model=deployment or self._chat_large_deployment,
                messages=list(messages),
                response_format=response_model,
                temperature=temperature,
            )
            parsed = resp.choices[0].message.parsed
            if parsed is not None:
                return parsed
            last_error = RuntimeError(
                f"AOAI structured response had parsed=None for {response_model.__name__}"
            )
        raise last_error or RuntimeError("chat_structured exhausted retries")

    async def embed(self, text: str | Sequence[str]) -> list[list[float]]:
        """Generate embeddings — returns one vector per input."""
        inputs: list[str] = [text] if isinstance(text, str) else list(text)
        resp = await self._client.embeddings.create(
            model=self._embeddings_deployment,
            input=inputs,
        )
        return [list(d.embedding) for d in resp.data]

    # ----- lifecycle -----

    async def close(self) -> None:
        await self._client.close()

    async def __aenter__(self) -> AzureOpenAIClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()
