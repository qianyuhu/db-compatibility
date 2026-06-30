"""
Execution Loop Data Schemas — typed structures for continuous fix engine.

Defines the complete data model for:
- Issue classification (5 categories)
- Issue lifecycle (NEW → IDENTIFIED → FIXING → FIXED → VERIFIED → RESOLVED)
- Fix strategies (4 types)
- Execution loop state and reporting
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# =========================================================================
# Enums
# =========================================================================


class IssueType(str, Enum):
    """Failure classification categories."""
    SQL_REWRITE = "SQL_REWRITE"          # LIMIT vs TOP, DATEPART mismatch, MERGE unsupported
    SCHEMA_MAPPING = "SCHEMA_MAPPING"    # datatype mismatch, nullability mismatch
    DATA_PRECISION = "DATA_PRECISION"    # decimal rounding, datetime truncation
    ORM_BEHAVIOR = "ORM_BEHAVIOR"        # query generation mismatch, lazy loading difference
    API_CONTRACT = "API_CONTRACT"        # response field mismatch, ordering differences


class IssueSeverity(str, Enum):
    """Issue severity for prioritization."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    BLOCKER = "BLOCKER"


class IssueStatus(str, Enum):
    """Issue lifecycle states.

    Flow: NEW → IDENTIFIED → FIXING → FIXED → VERIFIED → RESOLVED
    If reappears after RESOLVED: → REGRESSED
    """
    NEW = "NEW"              # Freshly detected, not yet classified
    IDENTIFIED = "IDENTIFIED"  # Classified with root cause
    FIXING = "FIXING"         # Fix strategy generated, being applied
    FIXED = "FIXED"           # Fix applied, awaiting verification
    VERIFIED = "VERIFIED"     # Fix confirmed by re-running affected tests
    RESOLVED = "RESOLVED"     # Fully resolved, no further action needed
    REGRESSED = "REGRESSED"   # Previously resolved, now reappeared


class FixType(str, Enum):
    """Types of fix strategies."""
    SQL_REWRITE = "SQL_REWRITE"              # Automatic dialect conversion
    SCHEMA_ADJUSTMENT = "SCHEMA_ADJUSTMENT"  # Type mapping correction
    DATA_NORMALIZATION = "DATA_NORMALIZATION"  # Precision rounding alignment
    QUERY_BEHAVIOR = "QUERY_BEHAVIOR"        # ORM adjustment rules


class LoopPhase(str, Enum):
    """Execution loop phases."""
    INIT = "INIT"
    RUNNING = "RUNNING"
    DETECTING = "DETECTING"
    CLASSIFYING = "CLASSIFYING"
    FIXING = "FIXING"
    RE_RUNNING = "RE_RUNNING"
    VERIFYING = "VERIFYING"
    STABILIZED = "STABILIZED"
    MAX_ITERATIONS = "MAX_ITERATIONS"


# =========================================================================
# Valid State Transitions
# =========================================================================

VALID_TRANSITIONS: dict[IssueStatus, list[IssueStatus]] = {
    IssueStatus.NEW:        [IssueStatus.IDENTIFIED],
    IssueStatus.IDENTIFIED: [IssueStatus.FIXING, IssueStatus.RESOLVED],
    IssueStatus.FIXING:     [IssueStatus.FIXED, IssueStatus.IDENTIFIED],
    IssueStatus.FIXED:      [IssueStatus.VERIFIED, IssueStatus.FIXING],
    IssueStatus.VERIFIED:   [IssueStatus.RESOLVED, IssueStatus.REGRESSED],
    IssueStatus.RESOLVED:   [IssueStatus.REGRESSED],
    IssueStatus.REGRESSED:  [IssueStatus.IDENTIFIED],
}


# =========================================================================
# Core Issue Types
# =========================================================================


@dataclass(frozen=True)
class MigrationIssue:
    """A single detected migration incompatibility.

    Every failure automatically becomes a tracked, fixable issue.
    System MUST NOT stop execution due to issues — only classify and fix.
    """
    issue_id: str                        # Unique identifier (UUID or hash)
    issue_type: IssueType                # Classification category
    severity: IssueSeverity              # LOW / MEDIUM / HIGH / BLOCKER
    status: IssueStatus = IssueStatus.NEW  # Lifecycle state

    # Source context
    test_id: str = ""                    # Originating test case ID
    test_name: str = ""                  # Human-readable test name
    source_db: str = ""                  # Source database type
    target_db: str = ""                  # Target database type

    # Issue details
    table_name: str = ""                 # Affected table (if applicable)
    field_name: str = ""                 # Affected field/column (if applicable)
    description: str = ""                # Human-readable description
    root_cause: str = ""                 # Root cause analysis
    diff_detail: dict[str, Any] = field(default_factory=dict)  # Original diff data

    # Fix tracking
    fix_strategy: FixStrategy | None = None  # Generated fix plan
    fix_attempts: int = 0                # Number of fix attempts
    affected_test_ids: list[str] = field(default_factory=list)  # Tests that need re-run

    # Timestamps
    detected_at: str = ""                # ISO timestamp when first detected
    fixed_at: str = ""                   # ISO timestamp when fix applied
    verified_at: str = ""                # ISO timestamp when verified

    def to_dict(self) -> dict[str, Any]:
        return {
            "issue_id": self.issue_id,
            "issue_type": self.issue_type.value if isinstance(self.issue_type, IssueType) else self.issue_type,
            "severity": self.severity.value if isinstance(self.severity, IssueSeverity) else self.severity,
            "status": self.status.value if isinstance(self.status, IssueStatus) else self.status,
            "test_id": self.test_id,
            "test_name": self.test_name,
            "source_db": self.source_db,
            "target_db": self.target_db,
            "table_name": self.table_name,
            "field_name": self.field_name,
            "description": self.description,
            "root_cause": self.root_cause,
            "diff_detail": self.diff_detail,
            "fix_strategy": self.fix_strategy.to_dict() if self.fix_strategy else None,
            "fix_attempts": self.fix_attempts,
            "affected_test_ids": self.affected_test_ids,
            "detected_at": self.detected_at,
            "fixed_at": self.fixed_at,
            "verified_at": self.verified_at,
        }


@dataclass(frozen=True)
class FixStrategy:
    """A fix plan for a single migration issue.

    Each strategy is a deterministic, repeatable plan:
    1. Detect the pattern
    2. Apply the transformation
    3. Validate the result
    4. Re-run affected tests
    """
    fix_type: FixType                    # SQL_REWRITE / SCHEMA_ADJUSTMENT / DATA_NORMALIZATION / QUERY_BEHAVIOR
    issue_id: str                        # Parent issue
    description: str = ""                # What this fix does
    steps: list[str] = field(default_factory=list)  # Ordered fix steps

    # SQL Rewrite specific
    original_sql: str = ""               # SQL before rewrite
    rewritten_sql: str = ""              # SQL after rewrite
    rewrite_rules: list[str] = field(default_factory=list)  # Applied rewrite rules

    # Schema specific
    source_type: str = ""                # Source column type (e.g. "NVARCHAR(MAX)")
    target_type: str = ""                # Target column type (e.g. "TEXT")
    type_mapping_rule: str = ""          # Applied type mapping rule

    # Estimated impact
    estimated_success_probability: float = 0.0  # 0.0-1.0
    affected_test_count: int = 0         # Number of tests affected
    is_reversible: bool = True           # Can the fix be undone?

    def to_dict(self) -> dict[str, Any]:
        return {
            "fix_type": self.fix_type.value if isinstance(self.fix_type, FixType) else self.fix_type,
            "issue_id": self.issue_id,
            "description": self.description,
            "steps": self.steps,
            "original_sql": self.original_sql,
            "rewritten_sql": self.rewritten_sql,
            "rewrite_rules": self.rewrite_rules,
            "source_type": self.source_type,
            "target_type": self.target_type,
            "type_mapping_rule": self.type_mapping_rule,
            "estimated_success_probability": self.estimated_success_probability,
            "affected_test_count": self.affected_test_count,
            "is_reversible": self.is_reversible,
        }


@dataclass(frozen=True)
class FixResult:
    """Result of applying a fix strategy."""
    issue_id: str
    fix_type: FixType
    success: bool
    message: str = ""
    before_state: dict[str, Any] = field(default_factory=dict)   # Snapshot before fix
    after_state: dict[str, Any] = field(default_factory=dict)    # Snapshot after fix
    re_run_results: list[dict[str, Any]] = field(default_factory=list)  # Results of re-running affected tests
    elapsed_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "issue_id": self.issue_id,
            "fix_type": self.fix_type.value if isinstance(self.fix_type, FixType) else self.fix_type,
            "success": self.success,
            "message": self.message,
            "before_state": self.before_state,
            "after_state": self.after_state,
            "re_run_results": self.re_run_results,
            "elapsed_ms": self.elapsed_ms,
        }


# =========================================================================
# Loop State Types
# =========================================================================


@dataclass(frozen=True)
class LoopIteration:
    """A single iteration of the execution loop."""
    iteration: int
    phase: LoopPhase
    tests_run: int
    tests_passed: int
    tests_failed: int
    issues_detected: int
    issues_fixed: int
    issues_verified: int
    elapsed_ms: float = 0.0
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "iteration": self.iteration,
            "phase": self.phase.value if isinstance(self.phase, LoopPhase) else self.phase,
            "tests_run": self.tests_run,
            "tests_passed": self.tests_passed,
            "tests_failed": self.tests_failed,
            "issues_detected": self.issues_detected,
            "issues_fixed": self.issues_fixed,
            "issues_verified": self.issues_verified,
            "elapsed_ms": self.elapsed_ms,
            "summary": self.summary,
        }


@dataclass
class ExecutionLoopState:
    """Mutable state tracking the entire execution loop lifecycle."""
    source_db: str
    target_db: str
    phase: LoopPhase = LoopPhase.INIT
    current_iteration: int = 0

    # Issue tracking
    issues: list[MigrationIssue] = field(default_factory=list)
    issue_index: dict[str, int] = field(default_factory=dict)  # issue_id → list index

    # Iteration history
    iterations: list[LoopIteration] = field(default_factory=list)

    # Fix tracking
    fix_results: list[FixResult] = field(default_factory=list)

    # Stabilization
    is_stabilized: bool = False
    max_iterations: int = 10
    stabilization_threshold: int = 2  # Consecutive clean runs to declare stable

    # Performance
    total_time_ms: float = 0.0
    started_at: str = ""
    ended_at: str = ""

    def add_issue(self, issue: MigrationIssue) -> int:
        """Add an issue and return its index."""
        idx = len(self.issues)
        self.issues.append(issue)
        self.issue_index[issue.issue_id] = idx
        return idx

    def get_issue(self, issue_id: str) -> MigrationIssue | None:
        """Get an issue by ID."""
        idx = self.issue_index.get(issue_id)
        if idx is not None and idx < len(self.issues):
            return self.issues[idx]
        return None

    def update_issue(self, issue_id: str, **kwargs: Any) -> MigrationIssue | None:
        """Create an updated copy of an issue (immutable pattern)."""
        idx = self.issue_index.get(issue_id)
        if idx is None or idx >= len(self.issues):
            return None

        old = self.issues[idx]
        # Build kwargs dict from old values, then override with new
        issue_dict = {
            "issue_id": old.issue_id,
            "issue_type": old.issue_type,
            "severity": old.severity,
            "status": old.status,
            "test_id": old.test_id,
            "test_name": old.test_name,
            "source_db": old.source_db,
            "target_db": old.target_db,
            "table_name": old.table_name,
            "field_name": old.field_name,
            "description": old.description,
            "root_cause": old.root_cause,
            "diff_detail": old.diff_detail,
            "fix_strategy": old.fix_strategy,
            "fix_attempts": old.fix_attempts,
            "affected_test_ids": old.affected_test_ids,
            "detected_at": old.detected_at,
            "fixed_at": old.fixed_at,
            "verified_at": old.verified_at,
        }
        issue_dict.update(kwargs)
        new_issue = MigrationIssue(**issue_dict)
        self.issues[idx] = new_issue
        return new_issue

    @property
    def total_issues(self) -> int:
        return len(self.issues)

    @property
    def open_issues(self) -> int:
        return sum(1 for i in self.issues
                   if i.status in (IssueStatus.NEW, IssueStatus.IDENTIFIED, IssueStatus.FIXING))

    @property
    def fixed_issues(self) -> int:
        return sum(1 for i in self.issues if i.status == IssueStatus.FIXED)

    @property
    def verified_issues(self) -> int:
        return sum(1 for i in self.issues if i.status == IssueStatus.VERIFIED)

    @property
    def resolved_issues(self) -> int:
        return sum(1 for i in self.issues if i.status == IssueStatus.RESOLVED)

    @property
    def regressed_issues(self) -> int:
        return sum(1 for i in self.issues if i.status == IssueStatus.REGRESSED)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_db": self.source_db,
            "target_db": self.target_db,
            "phase": self.phase.value if isinstance(self.phase, LoopPhase) else self.phase,
            "current_iteration": self.current_iteration,
            "total_issues": self.total_issues,
            "open_issues": self.open_issues,
            "fixed_issues": self.fixed_issues,
            "verified_issues": self.verified_issues,
            "resolved_issues": self.resolved_issues,
            "regressed_issues": self.regressed_issues,
            "is_stabilized": self.is_stabilized,
            "iterations": [it.to_dict() for it in self.iterations],
            "issues": [i.to_dict() for i in self.issues],
            "fix_results": [fr.to_dict() for fr in self.fix_results],
            "total_time_ms": self.total_time_ms,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
        }


# =========================================================================
# Execution Report
# =========================================================================


@dataclass(frozen=True)
class ExecutionReport:
    """Enhanced execution report replacing simple pass/fail.

    Every test has a richer status: PASS / PARTIAL_SUCCESS / FAIL / ERROR
    Every failure becomes a tracked issue with fix strategy.
    """
    # System-level summary
    source_db: str
    target_db: str
    total_iterations: int
    phase: str  # STABILIZED / MAX_ITERATIONS / RUNNING

    # Test results
    total_tests: int
    passed: int
    partial_success: int  # Tests that passed after fix
    failed: int
    errors: int
    success_rate: float  # (passed + partial_success) / total * 100

    # Issue summary
    total_issues: int
    issues_resolved: int
    issues_in_progress: int
    issues_regressed: int

    # Fix summary
    fixes_applied: int
    fixes_succeeded: int
    fixes_failed: int

    # Loop details
    iterations: list[LoopIteration] = field(default_factory=list)
    issues: list[MigrationIssue] = field(default_factory=list)
    fix_results: list[FixResult] = field(default_factory=list)

    # Recommendations
    recommendation: str = ""
    remaining_blockers: list[str] = field(default_factory=list)

    # Meta
    total_time_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "executive_summary": {
                "source_db": self.source_db,
                "target_db": self.target_db,
                "total_iterations": self.total_iterations,
                "phase": self.phase,
                "recommendation": self.recommendation,
            },
            "test_summary": {
                "total_tests": self.total_tests,
                "passed": self.passed,
                "partial_success": self.partial_success,
                "failed": self.failed,
                "errors": self.errors,
                "success_rate": self.success_rate,
            },
            "issue_summary": {
                "total_issues": self.total_issues,
                "issues_resolved": self.issues_resolved,
                "issues_in_progress": self.issues_in_progress,
                "issues_regressed": self.issues_regressed,
            },
            "fix_summary": {
                "fixes_applied": self.fixes_applied,
                "fixes_succeeded": self.fixes_succeeded,
                "fixes_failed": self.fixes_failed,
            },
            "iterations": [it.to_dict() for it in self.iterations],
            "issues": [i.to_dict() for i in self.issues],
            "fix_results": [fr.to_dict() for fr in self.fix_results],
            "remaining_blockers": self.remaining_blockers,
            "total_time_ms": self.total_time_ms,
        }
