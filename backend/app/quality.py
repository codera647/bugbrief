"""Conservative review hints. These checks never rewrite or certify model facts."""
import re

from .domain import Ticket

VERSION = "v2-grounded-review-1"


def review_findings(ticket: Ticket, source: str | None):
    findings = []

    def add(code, field, message):
        findings.append({"code": code, "field": field, "message": message})

    if source is None:
        add("source_unavailable", "source", "The original report is unavailable. Compare with the original before accepting factual claims.")
        return {"version": VERSION, "source_available": False, "findings": findings}
    lower = source.casefold()
    if re.search(r"\b(loses?|lost|disappears?|missing)\b", lower):
        for field in ("title", "actual_behavior"):
            text = (getattr(ticket, field) or "").casefold()
            positive = re.search(r"\b(retains?|keeps?|preserves?)\b", text)
            negative = re.search(r"\b(no|not|never|fails?|cannot|doesn't|without|loses?|lost|missing|disappears?)\b", text)
            if positive and not negative:
                add("possible_reversed_meaning", field, "The report describes lost or missing data, but this field says it is retained. Check that the bug's meaning is preserved.")
    # Unknown source intentions and paraphrases cannot be inferred reliably by regex.
    # Only identify explicit markers; missing markers lead to a review hint, not a verdict.
    expectation_markers = r"\b(expected?|expecting|should|supposed to|want(?:ed)?|intend(?:ed)?|need(?:ed)? to)\b"
    if ticket.expected_behavior_basis == "Reported" and not re.search(expectation_markers, lower):
        add("expectation_not_explicit", "expected_behavior_basis", "This is marked Reported, but no explicit expectation was found. Check whether it should be Inferred or Unknown.")
    if ticket.expected_behavior_basis == "Inferred" and re.search(r"\b(?:the|a) (?:page|button|screen|list|link|option)\b", lower) and not re.search(r"dashboard|chart|invoice|payment|account|integration|connection|sign.in|sav(?:e|ing|ed)|download", lower):
        add("vague_expected_result", "expected_behavior", "The report names a vague page or action. Confirm the intended result; Unknown may be more appropriate than an inferred goal.")
    if ticket.product_area != "Unknown":
        markers = {
            "Authentication": r"sign[ -]?(?:in|out)|log[ -]?(?:in|out)|account|password|verification|two.factor|invitation|email address",
            "Billing": r"bill(?:ing)?|invoice|payment|receipt|subscription|currency",
            "Dashboard": r"dashboard|chart|overview|summary tile",
            "Integrations": r"integrations?|connection|sync|stripe|slack|zapier|google sheets",
        }
        if not re.search(markers[ticket.product_area], lower):
            add("area_needs_evidence", "product_area", "The report does not clearly name this product area. Consider Unknown or confirm the feature with the reporter.")
    for key, value in ticket.reported_environment.model_dump().items():
        if key == "other_details":
            for detail in value:
                if detail.casefold() not in lower:
                    add("environment_detail_not_quoted", "reported_environment.other_details", "Some extra environment details are not quoted in the report. Check that they are facts rather than missing-information labels.")
                    break
        elif value and value.casefold() not in lower:
            add("environment_value_not_quoted", "reported_environment." + key, "This environment value is not quoted in the report. Verify it or leave it unknown.")
    browser_version = ticket.reported_environment.browser_version or ""
    if re.search(r"\b(?:ios|macos|windows|ubuntu|android|linux)\b", browser_version.casefold()):
        add("os_in_browser_version", "reported_environment.browser_version", "This browser version contains an operating-system name. Check the browser version and operating system separately.")
    if ticket.reported_steps:
        absent = [step for step in ticket.reported_steps if step.rstrip('.').casefold() not in lower]
        if absent:
            add("steps_need_comparison", "reported_steps", "Some steps are paraphrased or absent from the report. Keep only actions the reporter supplied.")
    if ticket.actual_behavior is None:
        add("actual_behavior_missing", "actual_behavior", "The observed behavior is missing. Describe the reported result without adding a cause.")
    return {"version": VERSION, "source_available": True, "findings": findings}
