"""
SP Execution Validator — validates compiled SPs against real databases.

Executes both the original MSSQL SP and the compiled target SP using the
existing DBAdapter infrastructure, then compares results via DiffEngine.

Usage:
    from architecture.core.sql.compiler.validator import SPValidator

    validator = SPValidator()
    diff = validator.validate(
        original_tsql=tsql_source,
        compiled_target_sql=compiled_code,
        source_db="mssql",
        target_db="kingbasees",
    )
    print(diff.status)  # MATCH / DIFF / ERROR
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.sandbox.adapter.factory import create_adapter
from app.sandbox.diff_engine import DiffEngine, DeterministicDiff
from app.sandbox.adapter.protocol import ExecuteResult


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SPExecutionDiff:
    """Difference between original MSSQL SP and compiled target SP execution.

    Attributes:
        status: "MATCH", "DIFF", or "ERROR"
        source_result: ExecuteResult from the source (MSSQL) SP execution.
        target_result: ExecuteResult from the target SP execution.
        diff_detail: DeterministicDiff from DiffEngine.compare().
        error: Error message if status is "ERROR".
    """
    status: str  # MATCH / DIFF / ERROR
    source_result: ExecuteResult | None = None
    target_result: ExecuteResult | None = None
    diff_detail: DeterministicDiff | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# SP Validator
# ---------------------------------------------------------------------------


class SPValidator:
    """Execute original and compiled SPs and compare results.

    Uses the existing DBAdapter factory and DiffEngine to validate
    that compiled SPs produce identical results to the original MSSQL SP.

    Usage:
        >>> validator = SPValidator()
        >>> diff = validator.validate(
        ...     original_tsql="CREATE PROCEDURE test AS SELECT 1 AS n",
        ...     compiled_target_sql="CREATE OR REPLACE FUNCTION test() ...",
        ...     target_db="kingbasees",
        ... )
    """

    def __init__(self) -> None:
        self.diff_engine = DiffEngine()

    def validate(
        self,
        original_tsql: str,
        compiled_target_sql: str,
        *,
        source_db: str = "mssql",
        target_db: str = "kingbasees",
        setup_sql: str | None = None,
        exec_sql: str | None = None,
        tolerance: dict[str, float] | None = None,
        ignore_fields: list[str] | None = None,
    ) -> SPExecutionDiff:
        """Execute both SPs and compare results.

        Pipeline:
            1. Create adapters for source and target databases
            2. Execute setup SQL (optional — e.g., table creation)
            3. Drop existing procedures (clean slate)
            4. Create the source SP on source DB
            5. Create the compiled SP on target DB
            6. Execute both SPs
            7. Compare results via DiffEngine

        Args:
            original_tsql: Original T-SQL stored procedure source.
            compiled_target_sql: Compiled target-dialect procedure code.
            source_db: Source database type (default "mssql").
            target_db: Target database type ("kingbasees" or "dm8").
            setup_sql: Optional SQL to run before SP creation (e.g., CREATE TABLE).
            exec_sql: Optional SQL to execute the SPs (default auto-detected).
            tolerance: Per-field numeric tolerance for comparison.
            ignore_fields: Field names to exclude from comparison.

        Returns:
            SPExecutionDiff with status, results, and diff detail.
        """
        src_adapter = None
        tgt_adapter = None

        try:
            # Create adapters
            src_adapter = create_adapter(source_db)
            tgt_adapter = create_adapter(target_db)

            # Execute setup SQL (e.g., create test tables)
            if setup_sql:
                src_result = src_adapter.execute_sql(setup_sql)
                if not src_result.success:
                    return SPExecutionDiff(
                        status="ERROR",
                        error=f"Setup SQL failed on {source_db}: {src_result.error}",
                    )
                tgt_result = tgt_adapter.execute_sql(setup_sql)
                if not tgt_result.success:
                    return SPExecutionDiff(
                        status="ERROR",
                        error=f"Setup SQL failed on {target_db}: {tgt_result.error}",
                    )

            # Drop existing procedures (clean slate)
            self._drop_procedure(src_adapter, "test_sp", source_db)
            self._drop_procedure(tgt_adapter, "test_sp", target_db)

            # Create the source SP
            src_create = src_adapter.execute_sql(original_tsql)
            if not src_create.success:
                return SPExecutionDiff(
                    status="ERROR",
                    source_result=src_create,
                    error=f"Failed to create source SP: {src_create.error}",
                )

            # Create the compiled target SP
            tgt_create = tgt_adapter.execute_sql(compiled_target_sql)
            if not tgt_create.success:
                return SPExecutionDiff(
                    status="ERROR",
                    source_result=src_create,
                    target_result=tgt_create,
                    error=f"Failed to create target SP: {tgt_create.error}",
                )

            # Execute the SPs
            src_exec_sql = exec_sql or self._get_exec_sql("test_sp", source_db)
            tgt_exec_sql = exec_sql or self._get_exec_sql("test_sp", target_db)

            src_exec = src_adapter.execute_sql(src_exec_sql)
            tgt_exec = tgt_adapter.execute_sql(tgt_exec_sql)

            if not src_exec.success:
                return SPExecutionDiff(
                    status="ERROR",
                    source_result=src_exec,
                    target_result=tgt_exec,
                    error=f"Source SP execution failed: {src_exec.error}",
                )

            if not tgt_exec.success:
                return SPExecutionDiff(
                    status="ERROR",
                    source_result=src_exec,
                    target_result=tgt_exec,
                    error=f"Target SP execution failed: {tgt_exec.error}",
                )

            # Compare results
            diff = self.diff_engine.compare(
                src_exec.to_dict(),
                tgt_exec.to_dict(),
                tolerance=tolerance,
                ignore_fields=ignore_fields,
            )

            status = "MATCH" if diff.status == "MATCH" else "DIFF"

            return SPExecutionDiff(
                status=status,
                source_result=src_exec,
                target_result=tgt_exec,
                diff_detail=diff,
            )

        except Exception as exc:
            return SPExecutionDiff(
                status="ERROR",
                error=f"{type(exc).__name__}: {exc}",
            )

        finally:
            # Clean up adapters
            if src_adapter:
                try:
                    src_adapter.close()
                except Exception:
                    pass
            if tgt_adapter:
                try:
                    tgt_adapter.close()
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _drop_procedure(adapter: Any, proc_name: str, db_type: str) -> None:
        """Drop an existing procedure if it exists.

        Uses dialect-specific DROP syntax.
        """
        try:
            if db_type == "mssql":
                adapter.execute_sql(
                    f"IF OBJECT_ID('{proc_name}', 'P') IS NOT NULL "
                    f"DROP PROCEDURE {proc_name}"
                )
            elif db_type == "kingbasees":
                adapter.execute_sql(
                    f"DROP FUNCTION IF EXISTS {proc_name}"
                )
            elif db_type == "dm8":
                adapter.execute_sql(
                    f"DROP PROCEDURE IF EXISTS {proc_name}"
                )
        except Exception:
            pass  # Best-effort cleanup

    @staticmethod
    def _get_exec_sql(proc_name: str, db_type: str) -> str:
        """Get the dialect-specific SQL to execute a procedure.

        Args:
            proc_name: Procedure/function name.
            db_type: Database type.

        Returns:
            SQL string to execute the procedure.
        """
        if db_type == "mssql":
            return f"EXEC {proc_name}"
        elif db_type == "kingbasees":
            return f"SELECT {proc_name}()"
        elif db_type == "dm8":
            return f"CALL {proc_name}()"
        return f"EXEC {proc_name}"


# ---------------------------------------------------------------------------
# Convenience: validate compilation result directly
# ---------------------------------------------------------------------------


def validate_compilation(
    original_tsql: str,
    compiled_code: str,
    target_db: str,
    **kwargs: Any,
) -> SPExecutionDiff:
    """Validate a compiled SP against the original T-SQL.

    Convenience wrapper around SPValidator.validate().

    Args:
        original_tsql: Original T-SQL SP source.
        compiled_code: Generated target-dialect code.
        target_db: Target database type.
        **kwargs: Passed to SPValidator.validate().

    Returns:
        SPExecutionDiff.
    """
    validator = SPValidator()
    return validator.validate(
        original_tsql=original_tsql,
        compiled_target_sql=compiled_code,
        source_db="mssql",
        target_db=target_db,
        **kwargs,
    )
