"""Pydantic schema gate — typed validation for LLM and tool I/O boundaries.

Per ``docs/ARCHITECTURE.md`` §3, the agent runs three guardrail gates;
the **schema gate** sits between the LLM (or any other untrusted input)
and the next node. Anything that goes through :func:`validate_schema` is
guaranteed to be a fully-validated Pydantic model on the way out, or
raises :class:`SchemaValidationError` on the way in.

This lives in its own module (rather than co-habiting with
:mod:`framework.guardrails.content_safety`) because the two gates have
nothing in common beyond the package: content safety calls the Azure
REST API; schema validation is pure Pydantic.

:class:`SchemaValidationError` carries either an underlying
:class:`pydantic.ValidationError` (the usual case — caller passed a
payload that fails the model's field rules) or just a free-form ``reason``
string (e.g. the LLM SDK returned ``parsed=None`` — there's no
:class:`ValidationError` to wrap, but the failure is still a schema
problem). Either way, callers see one exception class with
``.model`` and either ``.cause`` or ``.reason`` populated.

Phase 4: :class:`framework.agents.base.AgentBase` catches this exception
in the plan / route / reflect / tool nodes, emits a
:attr:`AgentEventType.SCHEMA_VALIDATION_FAILED` event with the model
name + attempt count + Pydantic error detail, and retries up to 2x
before propagating.
"""

from __future__ import annotations

from pydantic import BaseModel, ValidationError


class SchemaValidationError(Exception):
    """Raised when a structured payload fails Pydantic validation.

    Two construction shapes:

    * ``SchemaValidationError(MyModel, cause=validation_error)`` — the
      normal case, wrapping a real :class:`pydantic.ValidationError` from
      :meth:`pydantic.BaseModel.model_validate` or
      :meth:`pydantic.BaseModel.model_validate_json`.
    * ``SchemaValidationError(MyModel, reason="parsed=None")`` — the
      structured-LLM-SDK case, where the failure isn't a Pydantic
      ``ValidationError`` (e.g. the SDK couldn't even get to the
      validation step). ``reason`` documents what went wrong.

    Callers can introspect ``.model``, ``.cause`` (may be ``None``), and
    ``.reason`` (may be ``None``). The :class:`AgentBase` retry/emit
    helper uses ``.model.__name__`` for the event payload and falls back
    to ``.reason`` or ``str(.cause)`` for the error detail.
    """

    def __init__(
        self,
        model: type[BaseModel],
        cause: ValidationError | None = None,
        *,
        reason: str | None = None,
    ) -> None:
        if cause is None and reason is None:
            raise ValueError(
                "SchemaValidationError requires either a `cause` ValidationError "
                "or a `reason` string — got neither"
            )
        self.model = model
        self.cause = cause
        self.reason = reason
        detail = reason if reason is not None else str(cause)
        super().__init__(f"schema validation failed for {model.__name__}: {detail}")


def validate_schema[T: BaseModel](payload: object, model: type[T]) -> T:
    """Validate ``payload`` against ``model``.

    Accepts either an already-decoded object (dict, list, scalar) or a
    JSON string. Raises :class:`SchemaValidationError` (wrapping the
    underlying :class:`pydantic.ValidationError`) on failure so the agent
    layer can react with a retry or a ``SCHEMA_VALIDATION_FAILED`` event.
    """
    try:
        if isinstance(payload, str):
            return model.model_validate_json(payload)
        return model.model_validate(payload)
    except ValidationError as exc:
        raise SchemaValidationError(model, cause=exc) from exc
