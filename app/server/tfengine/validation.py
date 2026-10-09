"""Request validation (422) with contract-shaped `details`.

Pydantic (strict mode) checks each ticket; `TicketValidator` validates the envelope, collects
*every* failing item with its `index`, checks `ticket_id` uniqueness and translates Pydantic's
error types into the short `issue` strings used in the OpenAPI examples.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from pydantic_core import PydanticCustomError

from .errors import ErrorDetail, ValidationFailed

CHANNELS = ("email", "chat", "call_transcript")
_NON_WHITESPACE = re.compile(r"\S")


class TicketIn(BaseModel):
    """One ticket as defined by `PredictRequest` (strict: no int->str or null->"" coercion).

    Example:
        TicketIn.model_validate({"channel": "chat", "text": "order eka late"})
          -> TicketIn(ticket_id=None, channel="chat", subject="", text="order eka late")
        {"channel": "fax", "text": "hi"}  -> literal_error on "channel"
        {"channel": "chat", "text": "   "} -> blank_text on "text"
    """

    # extra="allow": the contract sets additionalProperties: true, so unknown keys are ignored, not rejected.
    model_config = ConfigDict(strict=True, extra="allow")

    ticket_id: str | None = Field(default=None, max_length=64)
    channel: Literal["email", "chat", "call_transcript"]
    subject: str = Field(default="", max_length=500)
    text: str = Field(min_length=1, max_length=10_000)

    @field_validator("text")
    @classmethod
    def _has_visible_char(cls, v: str) -> str:
        # Same rule as the schema's `pattern: '\S'`. Example: "\n\t " -> error; "🙂" -> ok
        if not _NON_WHITESPACE.search(v):
            raise PydanticCustomError("blank_text", "must contain at least one non-whitespace character")
        return v


@dataclass(frozen=True, slots=True)
class Ticket:
    """Validated, model-ready ticket (only the fields the model may see + the echo id).

    Example: Ticket(ticket_id="T1", channel="email", subject="Re: Order #4", text="Refund pls")
    """

    channel: str
    text: str
    subject: str = ""
    ticket_id: str | None = None

    def to_dict(self) -> dict:
        # Compact storage form for the job table. Example: {"i": "T1", "c": "chat", "s": "", "t": "..."}
        return {"i": self.ticket_id, "c": self.channel, "s": self.subject, "t": self.text}

    @classmethod
    def from_dict(cls, d: dict) -> "Ticket":
        return cls(ticket_id=d["i"], channel=d["c"], subject=d["s"], text=d["t"])


class TicketValidator:
    """Validates `/predict`, `/predict/batch` and `/batch/jobs` bodies.

    Example:
        v = TicketValidator(max_batch_items=100)
        v.single({"channel": "chat", "text": "hi"})          -> Ticket(...)
        v.many({"tickets": [{"ticket_id": "a", "channel": "chat", "text": " "},
                            {"channel": "chat", "text": "ok"}]}, max_items=100)
          -> 422 details=[{"index": 0, "field": "text", "issue": "must contain at least one non-whitespace character"},
                          {"index": 1, "field": "ticket_id", "issue": "is required"}]
    """

    # Pydantic error type -> contract wording (falls back to Pydantic's own message).
    _ISSUES = {
        "missing": "is required",
        "string_type": "must be a string",
        "literal_error": "must be one of " + ", ".join(CHANNELS),
        "string_too_short": "must contain at least one non-whitespace character",
        "model_type": "must be an object",
        "dict_type": "must be an object",
    }

    # Translate one Pydantic error into an ErrorDetail.
    # Example: {"type": "string_too_long", "loc": ("text",), "ctx": {"max_length": 10000}}
    #          -> ErrorDetail(field="text", issue="must be at most 10000 characters")
    def _detail(self, err: dict, index: int | None) -> ErrorDetail:
        field = ".".join(str(p) for p in err.get("loc", ())) or None
        etype = err.get("type", "")
        if etype == "string_too_long":
            issue = f"must be at most {err.get('ctx', {}).get('max_length')} characters"
        elif etype == "blank_text":
            issue = err["msg"]
        else:
            issue = self._ISSUES.get(etype, err.get("msg", "is invalid"))
        return ErrorDetail(field=field, issue=issue, index=index)

    def _check_item(self, raw: Any, index: int | None, require_id: bool) -> tuple[Ticket | None, list[ErrorDetail]]:
        # Validate one ticket; returns (ticket, []) or (None, [errors...]).
        if not isinstance(raw, dict):
            return None, [ErrorDetail(issue="must be a JSON object", index=index)]
        try:
            m = TicketIn.model_validate(raw)
        except ValidationError as e:
            errs = [self._detail(err, index) for err in e.errors(include_url=False)]
            # Batch items also need ticket_id; report it alongside other problems of the same item.
            if require_id and "ticket_id" not in raw:
                errs.append(ErrorDetail(field="ticket_id", issue="is required", index=index))
            return None, errs
        if require_id and m.ticket_id is None:
            return None, [ErrorDetail(field="ticket_id", issue="is required", index=index)]
        return Ticket(ticket_id=m.ticket_id, channel=m.channel, subject=m.subject, text=m.text), []

    def single(self, body: Any) -> Ticket:
        """`POST /predict` body -> Ticket, or 422."""
        if not isinstance(body, dict):
            raise ValidationFailed(details=[ErrorDetail(issue="request body must be a JSON object")])
        ticket, errs = self._check_item(body, index=None, require_id=False)
        if errs:
            raise ValidationFailed(details=errs)
        return ticket

    def many(self, body: Any, max_items: int) -> list[Ticket]:
        """`{"tickets": [...]}` body -> list[Ticket] (atomic: any bad item -> 422, nothing processed)."""
        # Envelope checks. Example: {"tickets": []} -> "must contain between 1 and 100 items"
        if not isinstance(body, dict):
            raise ValidationFailed(details=[ErrorDetail(issue="request body must be a JSON object")])
        if "tickets" not in body:
            raise ValidationFailed(details=[ErrorDetail(field="tickets", issue="is required")])
        items = body["tickets"]
        if not isinstance(items, list):
            raise ValidationFailed(details=[ErrorDetail(field="tickets", issue="must be an array")])
        if not 1 <= len(items) <= max_items:
            raise ValidationFailed(
                details=[ErrorDetail(field="tickets", issue=f"must contain between 1 and {max_items} items")]
            )

        # Per-item checks, collecting every failure (the contract wants all failing indexes).
        tickets: list[Ticket] = []
        errors: list[ErrorDetail] = []
        seen: set[str] = set()
        for i, raw in enumerate(items):
            ticket, errs = self._check_item(raw, index=i, require_id=True)
            if errs:
                errors.extend(errs)
                # Still remember its id so a later copy is reported as a duplicate too.
                if isinstance(raw, dict) and isinstance(raw.get("ticket_id"), str):
                    seen.add(raw["ticket_id"])
                continue
            # Example: ids ["a", "b", "a"] -> index 2: "duplicate of an earlier item"
            if ticket.ticket_id in seen:
                errors.append(ErrorDetail(field="ticket_id", issue="duplicate of an earlier item", index=i))
                continue
            seen.add(ticket.ticket_id)
            tickets.append(ticket)
        if errors:
            raise ValidationFailed(details=errors)
        return tickets
