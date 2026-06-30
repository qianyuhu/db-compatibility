"""
Issue Tracker — lifecycle state machine for migration issues.

Implements the full lifecycle:
    NEW → IDENTIFIED → FIXING → FIXED → VERIFIED → RESOLVED
    Any state → REGRESSED (if previously resolved issue reappears)

Features:
- State transition validation
- Regression detection (reappearing resolved issues)
- Statistics aggregation (open, fixed, verified, resolved, regressed)
- Timeline tracking (detected_at, fixed_at, verified_at)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .schemas import (
    VALID_TRANSITIONS,
    FixResult,
    FixStrategy,
    IssueSeverity,
    IssueStatus,
    IssueType,
    MigrationIssue,
)


class IssueTracker:
    """Manages the lifecycle of migration issues.

    Tracks each issue from detection through resolution, enforcing valid
    state transitions and detecting regressions.

    Usage:
        tracker = IssueTracker()
        tracker.register(issue)
        tracker.transition(issue_id, IssueStatus.FIXING)
        tracker.mark_fixed(issue_id, strategy)
        tracker.mark_verified(issue_id)
        tracker.mark_resolved(issue_id)
    """

    def __init__(self):
        self._issues: dict[str, MigrationIssue] = {}
        self._history: dict[str, list[dict[str, Any]]] = {}  # issue_id → transition log

    # =========================================================================
    # Registration
    # =========================================================================

    def register(self, issue: MigrationIssue) -> str:
        """Register a new issue. Returns the issue_id.

        If the issue already exists, checks for regression.
        """
        issue_id = issue.issue_id

        if issue_id in self._issues:
            existing = self._issues[issue_id]
            # Regression detection: resolved issue reappeared
            if existing.status == IssueStatus.RESOLVED:
                self._issues[issue_id] = MigrationIssue(
                    issue_id=existing.issue_id,
                    issue_type=existing.issue_type,
                    severity=existing.severity,
                    status=IssueStatus.REGRESSED,
                    test_id=existing.test_id,
                    test_name=existing.test_name,
                    source_db=existing.source_db,
                    target_db=existing.target_db,
                    table_name=existing.table_name,
                    field_name=existing.field_name,
                    description=issue.description,
                    root_cause=existing.root_cause,
                    diff_detail=issue.diff_detail,
                    fix_strategy=existing.fix_strategy,
                    fix_attempts=existing.fix_attempts + 1,
                    affected_test_ids=list(set(existing.affected_test_ids + issue.affected_test_ids)),
                    detected_at=existing.detected_at,
                    fixed_at=existing.fixed_at,
                    verified_at=existing.verified_at,
                )
                self._log_transition(issue_id, IssueStatus.REGRESSED,
                                     f"回归检测: 已解决的 issue 重新出现")
                return issue_id
            else:
                # Update existing issue with new diff detail
                self._issues[issue_id] = MigrationIssue(
                    issue_id=existing.issue_id,
                    issue_type=existing.issue_type,
                    severity=existing.severity,
                    status=existing.status,
                    test_id=existing.test_id,
                    test_name=existing.test_name,
                    source_db=existing.source_db,
                    target_db=existing.target_db,
                    table_name=existing.table_name,
                    field_name=existing.field_name,
                    description=issue.description or existing.description,
                    root_cause=existing.root_cause,
                    diff_detail=issue.diff_detail,
                    fix_strategy=existing.fix_strategy,
                    fix_attempts=existing.fix_attempts,
                    affected_test_ids=list(set(existing.affected_test_ids + issue.affected_test_ids)),
                    detected_at=existing.detected_at,
                    fixed_at=existing.fixed_at,
                    verified_at=existing.verified_at,
                )
                return issue_id

        # New issue
        self._issues[issue_id] = issue
        self._history[issue_id] = []
        self._log_transition(issue_id, IssueStatus.NEW,
                             f"新 issue 检测: {issue.description[:100]}")
        return issue_id

    def register_batch(self, issues: list[MigrationIssue]) -> list[str]:
        """Register multiple issues. Returns list of issue IDs."""
        return [self.register(issue) for issue in issues]

    # =========================================================================
    # State Transitions
    # =========================================================================

    def transition(self, issue_id: str, new_status: IssueStatus) -> bool:
        """Transition an issue to a new status. Validates the transition.

        Returns True if the transition is valid and applied.
        """
        if issue_id not in self._issues:
            return False

        current = self._issues[issue_id]
        current_status = current.status

        # Validate transition
        valid_next = VALID_TRANSITIONS.get(current_status, [])
        if new_status not in valid_next:
            # Special case: anything can go to REGRESSED
            if new_status == IssueStatus.REGRESSED:
                pass  # Allow
            else:
                return False  # Invalid transition

        # Apply transition
        now = datetime.now(timezone.utc).isoformat()
        kwargs: dict[str, Any] = {"status": new_status}

        if new_status == IssueStatus.FIXED:
            kwargs["fixed_at"] = now
        elif new_status == IssueStatus.VERIFIED:
            kwargs["verified_at"] = now

        self._issues[issue_id] = MigrationIssue(
            issue_id=current.issue_id,
            issue_type=current.issue_type,
            severity=current.severity,
            status=new_status,
            test_id=current.test_id,
            test_name=current.test_name,
            source_db=current.source_db,
            target_db=current.target_db,
            table_name=current.table_name,
            field_name=current.field_name,
            description=current.description,
            root_cause=current.root_cause,
            diff_detail=current.diff_detail,
            fix_strategy=current.fix_strategy,
            fix_attempts=current.fix_attempts,
            affected_test_ids=current.affected_test_ids,
            detected_at=current.detected_at,
            fixed_at=kwargs.get("fixed_at", current.fixed_at),
            verified_at=kwargs.get("verified_at", current.verified_at),
        )

        self._log_transition(issue_id, new_status,
                             f"状态变更: {current_status.value} → {new_status.value}")
        return True

    # =========================================================================
    # Convenience Methods
    # =========================================================================

    def mark_identified(self, issue_id: str) -> bool:
        """Mark issue as IDENTIFIED (classified with root cause)."""
        return self.transition(issue_id, IssueStatus.IDENTIFIED)

    def mark_fixing(self, issue_id: str, strategy: FixStrategy | None = None) -> bool:
        """Mark issue as FIXING and attach a fix strategy."""
        if issue_id in self._issues and strategy:
            current = self._issues[issue_id]
            self._issues[issue_id] = MigrationIssue(
                issue_id=current.issue_id,
                issue_type=current.issue_type,
                severity=current.severity,
                status=current.status,
                test_id=current.test_id,
                test_name=current.test_name,
                source_db=current.source_db,
                target_db=current.target_db,
                table_name=current.table_name,
                field_name=current.field_name,
                description=current.description,
                root_cause=current.root_cause,
                diff_detail=current.diff_detail,
                fix_strategy=strategy,
                fix_attempts=current.fix_attempts,
                affected_test_ids=current.affected_test_ids,
                detected_at=current.detected_at,
                fixed_at=current.fixed_at,
                verified_at=current.verified_at,
            )
        return self.transition(issue_id, IssueStatus.FIXING)

    def mark_fixed(self, issue_id: str) -> bool:
        """Mark issue as FIXED (fix applied, awaiting verification)."""
        if issue_id in self._issues:
            current = self._issues[issue_id]
            self._issues[issue_id] = MigrationIssue(
                issue_id=current.issue_id,
                issue_type=current.issue_type,
                severity=current.severity,
                status=current.status,
                test_id=current.test_id,
                test_name=current.test_name,
                source_db=current.source_db,
                target_db=current.target_db,
                table_name=current.table_name,
                field_name=current.field_name,
                description=current.description,
                root_cause=current.root_cause,
                diff_detail=current.diff_detail,
                fix_strategy=current.fix_strategy,
                fix_attempts=current.fix_attempts + 1,
                affected_test_ids=current.affected_test_ids,
                detected_at=current.detected_at,
                fixed_at=current.fixed_at,
                verified_at=current.verified_at,
            )
        return self.transition(issue_id, IssueStatus.FIXED)

    def mark_verified(self, issue_id: str) -> bool:
        """Mark issue as VERIFIED (fix confirmed by re-running tests)."""
        return self.transition(issue_id, IssueStatus.VERIFIED)

    def mark_resolved(self, issue_id: str) -> bool:
        """Mark issue as RESOLVED (fully resolved, no further action)."""
        return self.transition(issue_id, IssueStatus.RESOLVED)

    def mark_regressed(self, issue_id: str) -> bool:
        """Mark issue as REGRESSED (previously resolved, now reappeared)."""
        return self.transition(issue_id, IssueStatus.REGRESSED)

    # =========================================================================
    # Query Methods
    # =========================================================================

    def get(self, issue_id: str) -> MigrationIssue | None:
        """Get an issue by ID."""
        return self._issues.get(issue_id)

    def get_all(self) -> list[MigrationIssue]:
        """Get all tracked issues."""
        return list(self._issues.values())

    def get_by_status(self, status: IssueStatus) -> list[MigrationIssue]:
        """Get issues filtered by status."""
        return [i for i in self._issues.values() if i.status == status]

    def get_by_type(self, issue_type: IssueType) -> list[MigrationIssue]:
        """Get issues filtered by type."""
        return [i for i in self._issues.values() if i.issue_type == issue_type]

    def get_by_severity(self, severity: IssueSeverity) -> list[MigrationIssue]:
        """Get issues filtered by severity."""
        return [i for i in self._issues.values() if i.severity == severity]

    def get_by_test(self, test_id: str) -> list[MigrationIssue]:
        """Get issues originating from a specific test."""
        return [i for i in self._issues.values() if i.test_id == test_id]

    # =========================================================================
    # Statistics
    # =========================================================================

    @property
    def total(self) -> int:
        return len(self._issues)

    @property
    def open_count(self) -> int:
        return sum(1 for i in self._issues.values()
                   if i.status in (IssueStatus.NEW, IssueStatus.IDENTIFIED, IssueStatus.FIXING))

    @property
    def fixed_count(self) -> int:
        return sum(1 for i in self._issues.values() if i.status == IssueStatus.FIXED)

    @property
    def verified_count(self) -> int:
        return sum(1 for i in self._issues.values() if i.status == IssueStatus.VERIFIED)

    @property
    def resolved_count(self) -> int:
        return sum(1 for i in self._issues.values() if i.status == IssueStatus.RESOLVED)

    @property
    def regressed_count(self) -> int:
        return sum(1 for i in self._issues.values() if i.status == IssueStatus.REGRESSED)

    def stats(self) -> dict[str, int]:
        """Get full statistics."""
        return {
            "total": self.total,
            "open": self.open_count,
            "fixed": self.fixed_count,
            "verified": self.verified_count,
            "resolved": self.resolved_count,
            "regressed": self.regressed_count,
        }

    # =========================================================================
    # History
    # =========================================================================

    def get_history(self, issue_id: str) -> list[dict[str, Any]]:
        """Get the transition history for an issue."""
        return self._history.get(issue_id, [])

    def _log_transition(self, issue_id: str, status: IssueStatus, message: str) -> None:
        """Record a state transition."""
        if issue_id not in self._history:
            self._history[issue_id] = []
        self._history[issue_id].append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": status.value if isinstance(status, IssueStatus) else status,
            "message": message,
        })

    # =========================================================================
    # Reset
    # =========================================================================

    def reset(self) -> None:
        """Clear all tracked issues and history."""
        self._issues.clear()
        self._history.clear()
