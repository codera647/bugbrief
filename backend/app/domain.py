import hashlib
import json
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=240)]
ProductArea = Literal["Authentication", "Billing", "Dashboard", "Integrations", "Unknown"]
Role = Literal["viewer", "contributor", "owner"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Environment(StrictModel):
    browser: ShortText | None
    browser_version: ShortText | None
    operating_system: ShortText | None
    app_version: ShortText | None
    other_details: list[ShortText] = Field(max_length=10)


class Ticket(StrictModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    product_area: ProductArea
    product_area_evidence: ShortText | None
    actual_behavior: Text | None
    expected_behavior: Text | None
    expected_behavior_basis: Literal["Reported", "Inferred", "Unknown"]
    reported_environment: Environment
    reported_steps: list[ShortText] | None = Field(max_length=10)
    missing_information: list[ShortText] = Field(max_length=10)
    follow_up_questions: list[ShortText] = Field(max_length=3)

    @model_validator(mode="after")
    def semantics(self):
        if (self.expected_behavior is None) != (self.expected_behavior_basis == "Unknown"):
            raise ValueError("Use Unknown only when expected behavior is not supplied")
        if self.product_area != "Unknown" and not self.product_area_evidence:
            raise ValueError("A suggested product area needs an excerpt from the report")
        for values in (self.reported_steps or [], self.missing_information, self.follow_up_questions):
            normalized = [s.casefold() for s in values]
            if len(normalized) != len(set(normalized)):
                raise ValueError("Repeated list items are not allowed")
        return self

    def check_source(self, source: str | None):
        if source is not None and self.product_area_evidence and self.product_area_evidence not in source:
            raise ValueError("Product-area evidence must be an exact excerpt from the customer report")


class GenerateRequest(StrictModel):
    report: Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=4000)]
    operation_id: str = Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")


class SaveRequest(StrictModel):
    payload: Ticket
    operation_id: str = Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    job_id: str | None = None
    save_source: bool = False


class UpdateRequest(StrictModel):
    payload: Ticket
    expected_revision: int = Field(ge=1)


class RevisionRequest(StrictModel):
    expected_revision: int = Field(ge=1)


class SessionReviewRequest(StrictModel):
    payload: Ticket
    job_id: str


class DraftChecksRequest(StrictModel):
    payload: Ticket
    job_id: str | None = None
    ticket_id: str | None = None

    @model_validator(mode="after")
    def one_source(self):
        if bool(self.job_id) == bool(self.ticket_id):
            raise ValueError("Supply exactly one job_id or ticket_id")
        return self


class SessionExportRequest(StrictModel):
    payload: Ticket
    receipt_id: str
    format: Literal["json", "text"]


def digest(ticket: Ticket) -> str:
    canonical = json.dumps(ticket.model_dump(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def export_text(ticket: Ticket) -> str:
    environment = ticket.reported_environment.model_dump()
    env_lines = [f"{key.replace('_', ' ').capitalize()}: {value}" for key, value in environment.items() if value and key != "other_details"]
    env_lines.extend(environment["other_details"])
    sections = [
        ticket.title,
        f"Product area: {ticket.product_area}",
        f"Evidence: {ticket.product_area_evidence or 'Not established'}",
        f"Actual behavior\n{ticket.actual_behavior or 'Not reported'}",
        f"Expected behavior ({ticket.expected_behavior_basis})\n{ticket.expected_behavior or 'Not reported'}",
        "Reported environment\n" + ("\n".join(env_lines) or "Not reported"),
        "Reported steps\n" + ("\n".join(f"{i + 1}. {step}" for i, step in enumerate(ticket.reported_steps or [])) or "Not reported"),
        "Missing information\n" + ("\n".join(f"- {s}" for s in ticket.missing_information) or "None listed"),
        "Follow-up questions\n" + ("\n".join(f"- {s}" for s in ticket.follow_up_questions) or "None"),
    ]
    return "\n\n".join(sections)


def uuid_string(value: str) -> str:
    return str(UUID(value))
