"""Machine-readable error categories for LABELOS production automation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

# Canonical error categories (Section 23).
INPUT_ERROR = "INPUT_ERROR"
SYSTEM_ERROR = "SYSTEM_ERROR"
ILLUSTRATOR_ERROR = "ILLUSTRATOR_ERROR"
ARTWORK_GENERATION_ERROR = "ARTWORK_GENERATION_ERROR"
LABEL_VALIDATION_FAILURE = "LABEL_VALIDATION_FAILURE"
PACKAGE_ERROR = "PACKAGE_ERROR"
PACKAGE_VERIFICATION_FAILED = "PACKAGE_VERIFICATION_FAILED"
PREPRESS_ERROR = "PREPRESS_ERROR"
APPROVAL_ERROR = "APPROVAL_ERROR"
STORAGE_ERROR = "STORAGE_ERROR"
NOTIFICATION_ERROR = "NOTIFICATION_ERROR"

# Lifecycle / operational statuses.
DUPLICATE_SKIPPED = "DUPLICATE_SKIPPED"
REJECTED_VALIDATION = "REJECTED_VALIDATION"
REJECTED_BY_APPROVER = "REJECTED_BY_APPROVER"
CORRECTION_REQUIRED = "CORRECTION_REQUIRED"


@dataclass
class LabelosError:
    """Structured error returned to API / n8n clients."""

    code: str
    category: str
    message: str
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if payload["details"] is None:
            del payload["details"]
        return payload


class LabelosException(Exception):
    """Raised for fail-closed operational errors with a machine-readable code."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        category: str,
        details: dict[str, Any] | None = None,
        http_status: int = 400,
    ) -> None:
        super().__init__(message)
        self.error = LabelosError(code=code, category=category, message=message, details=details)
        self.http_status = http_status
