"""Label production lifecycle states."""

from __future__ import annotations

from enum import Enum


class JobLifecycle(str, Enum):
    DRAFT = "DRAFT"
    DATA_READY = "DATA_READY"
    ARTWORK_GENERATED = "ARTWORK_GENERATED"
    ARTWORK_REVIEW = "ARTWORK_REVIEW"
    TECHNICALLY_VALIDATED = "TECHNICALLY_VALIDATED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED_FOR_PRODUCTION = "APPROVED_FOR_PRODUCTION"
    RELEASED = "RELEASED"
    ARCHIVED = "ARCHIVED"
    CORRECTION_REQUIRED = "CORRECTION_REQUIRED"
    REJECTED_VALIDATION = "REJECTED_VALIDATION"
    REJECTED_BY_APPROVER = "REJECTED_BY_APPROVER"
    PACKAGE_VERIFICATION_FAILED = "PACKAGE_VERIFICATION_FAILED"
    DUPLICATE_SKIPPED = "DUPLICATE_SKIPPED"


# Allowed transitions including backward correction paths.
LIFECYCLE_TRANSITIONS: dict[JobLifecycle, set[JobLifecycle]] = {
    JobLifecycle.DRAFT: {JobLifecycle.DATA_READY, JobLifecycle.DUPLICATE_SKIPPED},
    JobLifecycle.DATA_READY: {
        JobLifecycle.ARTWORK_GENERATED,
        JobLifecycle.ARTWORK_REVIEW,
        JobLifecycle.TECHNICALLY_VALIDATED,
        JobLifecycle.REJECTED_VALIDATION,
        JobLifecycle.CORRECTION_REQUIRED,
    },
    JobLifecycle.ARTWORK_GENERATED: {
        JobLifecycle.ARTWORK_REVIEW,
        JobLifecycle.TECHNICALLY_VALIDATED,
        JobLifecycle.REJECTED_VALIDATION,
        JobLifecycle.CORRECTION_REQUIRED,
    },
    JobLifecycle.ARTWORK_REVIEW: {
        JobLifecycle.TECHNICALLY_VALIDATED,
        JobLifecycle.CORRECTION_REQUIRED,
        JobLifecycle.REJECTED_VALIDATION,
    },
    JobLifecycle.CORRECTION_REQUIRED: {
        JobLifecycle.DATA_READY,
        JobLifecycle.ARTWORK_GENERATED,
        JobLifecycle.DRAFT,
    },
    JobLifecycle.TECHNICALLY_VALIDATED: {
        JobLifecycle.AWAITING_APPROVAL,
        JobLifecycle.CORRECTION_REQUIRED,
        JobLifecycle.PACKAGE_VERIFICATION_FAILED,
    },
    JobLifecycle.AWAITING_APPROVAL: {
        JobLifecycle.APPROVED_FOR_PRODUCTION,
        JobLifecycle.REJECTED_BY_APPROVER,
        JobLifecycle.PACKAGE_VERIFICATION_FAILED,
    },
    JobLifecycle.REJECTED_BY_APPROVER: {
        JobLifecycle.CORRECTION_REQUIRED,
        JobLifecycle.AWAITING_APPROVAL,
    },
    JobLifecycle.APPROVED_FOR_PRODUCTION: {JobLifecycle.RELEASED},
    JobLifecycle.RELEASED: {JobLifecycle.ARCHIVED},
    JobLifecycle.REJECTED_VALIDATION: {JobLifecycle.CORRECTION_REQUIRED},
    JobLifecycle.PACKAGE_VERIFICATION_FAILED: {JobLifecycle.CORRECTION_REQUIRED},
    JobLifecycle.DUPLICATE_SKIPPED: set(),
    JobLifecycle.ARCHIVED: set(),
}
