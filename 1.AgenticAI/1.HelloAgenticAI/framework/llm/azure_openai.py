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

from framework.guardrails.schema import SchemaValidationError

T = TypeVar("T", bound=BaseModel)


class AzureOpenAIClient:
    """Async Azure OpenAI client wrapper with typed methods."""

    # 2024-10-21 (GA) returned 401 PermissionDenied for the dev principal on
    # the swedencentral account even with a correct AAD bearer token; the
    # 2024-10-01-preview surface works and supports chat.completions.parse.
    # See ADR-0003 risk #7 for the empirical investigation.
    DEFAULT_API_VERSION = "2024-10-01-preview"
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

        Uses OpenAI's structured-outputs (``response_format=<Model>``) API,
        which forces the model to return JSON matching the schema at the
        SDK level — the only way validation fails here is if the SDK
        itself can't deserialise, in which case ``parsed`` is ``None``.

        Retries up to ``max_retries`` extra times on ``parsed=None`` (rare
        but possible for ambiguous schemas). Phase 4: raises
        :class:`SchemaValidationError` (not ``RuntimeError``) after
        retries exhaust, so the :class:`framework.agents.base.AgentBase`
        retry/emit helper can catch it uniformly with tool-input
        ``ValidationError``\\s and emit
        :attr:`AgentEventType.SCHEMA_VALIDATION_FAILED`. Callers that
        catch the legacy ``RuntimeError`` need to update.
        """
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
        raise SchemaValidationError(
            response_model,
            reason=(f"AOAI structured response had parsed=None after {max_retries + 1} attempt(s)"),
        )

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
