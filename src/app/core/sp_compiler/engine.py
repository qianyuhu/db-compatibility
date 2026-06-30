"""
SP Compiler Engine — main pipeline orchestrator.

Pipeline:
    T-SQL SP Text
       ↓ 1. Preprocess: extract procedure name, split header from body
       ↓ 2. Tokenize: T-SQL lexer
       ↓ 3. Segment: block segmentation
       ↓ 4. Extract: blocks → IR nodes (sqlglot for SQL statements only)
       ↓ 5. Build: assemble and validate IRProcedure
       ↓ 6. Generate: IR → target dialect code

Usage:
    from app.core.sp_compiler import compile_sp

    result = compile_sp(tsql_text, target_db="kingbasees")
    if result.success:
        print(result.generated_code)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .ir import IRProcedure
from .parser import (
    SegmentationError,
    LexerError,
    segment_blocks,
    tokenize,
)
from .parser.control_flow_extractor import (
    ExtractionError,
    extract_ir_nodes,
)
from .builder import build_procedure, IRBuildError
from .generator import create_generator, list_generators
from .ir import IRVariable, VariableScope


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CompilationResult:
    """Result of a complete SP compilation pipeline.

    This is the single output type for compile_sp() — consumers never
    receive exceptions; all errors are collected in the errors field.

    Attributes:
        success: True if the SP was successfully compiled.
        original_source: Original T-SQL source text.
        procedure_name: Extracted procedure name.
        ir: The intermediate representation (None if compilation failed early).
        generated_code: Generated target-dialect procedure code.
        target_db: Target database type ("kingbasees" or "dm8").
        errors: Error messages (one per pipeline stage failure).
        warnings: Non-fatal warning messages.
        token_count: Number of tokens produced by lexer.
        block_count: Number of semantic blocks produced by segmenter.
        ir_node_count: Number of IR nodes in the procedure body.
    """
    success: bool
    original_source: str = ""
    procedure_name: str = ""
    ir: IRProcedure | None = None
    generated_code: str = ""
    target_db: str = ""
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    token_count: int = 0
    block_count: int = 0
    ir_node_count: int = 0


# ---------------------------------------------------------------------------
# Compiler class
# ---------------------------------------------------------------------------


class SPCompiler:
    """Main compiler pipeline: T-SQL SP → IR → Target Code.

    The compiler is stateless other than the target_db field.
    Each call to compile() creates all intermediate data fresh.
    All IR nodes are frozen dataclasses — safe for concurrent use.

    Usage:
        >>> compiler = SPCompiler(target_db="kingbasees")
        >>> result = compiler.compile(tsql_text)
        >>> if result.success:
        ...     print(result.generated_code)
    """

    def __init__(self, target_db: str) -> None:
        """Initialize the compiler for a specific target database.

        Args:
            target_db: Target database type ("kingbasees" or "dm8").
        """
        if target_db not in list_generators():
            available = list_generators()
            raise ValueError(
                f"Unsupported target database: '{target_db}'. "
                f"Available: {available}"
            )
        self.target_db = target_db

    def compile(self, tsql_text: str) -> CompilationResult:
        """Compile a T-SQL stored procedure to the target dialect.

        This is the main entry point. Each pipeline stage is called in
        sequence; if any stage fails, a CompilationResult with success=False
        is returned immediately with the error diagnostics.

        Args:
            tsql_text: Complete T-SQL stored procedure source code, including
                       CREATE PROCEDURE header.

        Returns:
            CompilationResult with generated code and diagnostics.
        """
        warnings: list[str] = []

        if not tsql_text or not tsql_text.strip():
            return CompilationResult(
                success=False,
                original_source=tsql_text,
                errors=["Empty input"],
            )

        tsql_text = tsql_text.strip()

        # ------------------------------------------------------------------
        # Stage 0: Preprocess — extract name and parameters
        # ------------------------------------------------------------------
        name, params, body_text = self._extract_header(tsql_text)

        if not body_text.strip():
            return CompilationResult(
                success=False,
                original_source=tsql_text,
                procedure_name=name or "",
                errors=["No procedure body found after CREATE PROCEDURE header"],
            )

        # ------------------------------------------------------------------
        # Stage 1: Tokenize
        # ------------------------------------------------------------------
        try:
            tokens = tokenize(body_text)
        except LexerError as exc:
            return CompilationResult(
                success=False,
                original_source=tsql_text,
                procedure_name=name or "",
                errors=[f"Lexer error: {exc.message} at line {exc.line}"],
            )

        token_count = len([t for t in tokens if t.type.value != "EOF"])

        # ------------------------------------------------------------------
        # Stage 2: Segment
        # ------------------------------------------------------------------
        try:
            blocks = segment_blocks(tokens)
        except SegmentationError as exc:
            return CompilationResult(
                success=False,
                original_source=tsql_text,
                procedure_name=name or "",
                errors=[f"Segmentation error: {exc}"],
                token_count=token_count,
            )

        block_count = len(blocks)

        # ------------------------------------------------------------------
        # Stage 3: Extract IR nodes
        # ------------------------------------------------------------------
        try:
            ir_nodes = extract_ir_nodes(blocks)
        except ExtractionError as exc:
            return CompilationResult(
                success=False,
                original_source=tsql_text,
                procedure_name=name or "",
                errors=[f"Extraction error: {exc}"],
                token_count=token_count,
                block_count=block_count,
            )

        ir_node_count = len(ir_nodes)

        # ------------------------------------------------------------------
        # Stage 4: Build IRProcedure
        # ------------------------------------------------------------------
        try:
            ir = build_procedure(
                name=name or "migrated_sp",
                parameters=params,
                body=ir_nodes,
                original_source=tsql_text,
            )
        except IRBuildError as exc:
            return CompilationResult(
                success=False,
                original_source=tsql_text,
                procedure_name=name or "",
                errors=[f"IR build error: {exc}"],
                token_count=token_count,
                block_count=block_count,
                ir_node_count=ir_node_count,
            )

        # ------------------------------------------------------------------
        # Stage 5: Generate target code
        # ------------------------------------------------------------------
        try:
            generator = create_generator(self.target_db)
            generated_code = generator.generate(ir)
        except Exception as exc:
            return CompilationResult(
                success=False,
                original_source=tsql_text,
                procedure_name=name or "",
                ir=ir,
                target_db=self.target_db,
                errors=[f"Code generation error: {type(exc).__name__}: {exc}"],
                warnings=warnings,
                token_count=token_count,
                block_count=block_count,
                ir_node_count=ir_node_count,
            )

        # ------------------------------------------------------------------
        # Success
        # ------------------------------------------------------------------
        return CompilationResult(
            success=True,
            original_source=tsql_text,
            procedure_name=ir.name,
            ir=ir,
            generated_code=generated_code,
            target_db=self.target_db,
            warnings=warnings,
            token_count=token_count,
            block_count=block_count,
            ir_node_count=ir_node_count,
        )

    # ------------------------------------------------------------------
    # Header extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_header(
        tsql: str,
    ) -> tuple[str | None, list[IRVariable], str]:
        """Extract procedure name, parameters, and body from CREATE PROCEDURE.

        Parses:
            CREATE [OR ALTER] PROCEDURE [schema.]name
                [@param1 TYPE [= default] [OUTPUT], ...]
            [WITH option [,...]]
            AS
            <body>

        Returns:
            Tuple of (name, parameters, body_text).
        """
        # Match CREATE PROCEDURE header
        # Pattern captures: full header up to AS, procedure name
        header_pattern = r"""
            CREATE\s+(?:OR\s+ALTER\s+)?PROCEDURE\s+
            (?:\[?[a-zA-Z_][a-zA-Z0-9_]*\]?\.)?   # optional schema
            \[?([a-zA-Z_][a-zA-Z0-9_]*)\]?         # procedure name (capture group 1)
            (.*?)                                    # parameters and options (capture group 2)
            \bAS\b\s*                                # AS keyword
        """

        match = re.search(
            header_pattern,
            tsql.strip(),
            re.IGNORECASE | re.DOTALL | re.VERBOSE,
        )

        if not match:
            # No CREATE PROCEDURE header — treat entire text as body
            return None, [], tsql.strip()

        name = match.group(1)
        params_section = match.group(2).strip()
        body = tsql[match.end():].strip()

        # Parse parameters from the section between name and AS
        parameters = SPCompiler._parse_parameters(params_section)

        return name, parameters, body

    @staticmethod
    def _parse_parameters(params_section: str) -> list[IRVariable]:
        """Parse @param TYPE [= default] [OUTPUT] from procedure header.

        Args:
            params_section: Text between procedure name and AS keyword.

        Returns:
            List of IRVariable nodes with scope=PARAMETER.
        """
        if not params_section.strip():
            return []

        # Remove outer parentheses if present
        section = params_section.strip()
        if section.startswith("(") and section.endswith(")"):
            section = section[1:-1].strip()

        # Remove WITH options (e.g., WITH ENCRYPTION, WITH RECOMPILE)
        with_match = re.search(r"\bWITH\b\s+\w+", section, re.IGNORECASE)
        if with_match:
            section = section[:with_match.start()].strip()

        parameters: list[IRVariable] = []

        # Split on commas that are not inside parentheses
        param_parts = _split_params(section)

        for part in param_parts:
            part = part.strip()
            if not part:
                continue

            param = SPCompiler._parse_single_parameter(part)
            if param:
                parameters.append(param)

        return parameters

    @staticmethod
    def _parse_single_parameter(param_text: str) -> IRVariable | None:
        """Parse a single parameter declaration like '@id INT OUTPUT' or '@name VARCHAR(100) = 'default''

        Returns IRVariable or None if parsing fails.
        """
        text = param_text.strip()

        # Find @variable
        var_match = re.match(r"@(\w+)", text)
        if not var_match:
            return None

        var_name = var_match.group(1)
        remainder = text[var_match.end():].strip()

        # Check for OUTPUT
        is_output = False
        if re.search(r"\bOUTPUT\b", remainder, re.IGNORECASE) or \
           re.search(r"\bOUT\b", remainder, re.IGNORECASE):
            is_output = True
            remainder = re.sub(r"\bOUTPUT\b", "", remainder, flags=re.IGNORECASE).strip()
            remainder = re.sub(r"\bOUT\b", "", remainder, flags=re.IGNORECASE).strip()

        # Extract data type
        # Data type could be: INT, VARCHAR(100), DECIMAL(10,2), etc.
        type_match = re.match(
            r"(\w+(?:\s*\([^)]*\))?(?:\s*\w+(?:\s*\([^)]*\))?)*)",
            remainder
        )
        if type_match:
            data_type = type_match.group(1).strip()
            remainder = remainder[type_match.end():].strip()
        else:
            data_type = remainder.split()[0] if remainder.split() else "VARCHAR"
            remainder = " ".join(remainder.split()[1:]) if remainder.split() else ""

        # Check for DEFAULT / = value
        default_value: str | None = None
        if remainder.upper().startswith("DEFAULT"):
            default_value = remainder[7:].strip()
        elif remainder.startswith("="):
            default_value = remainder[1:].strip()

        return IRVariable(
            name=var_name,
            data_type=data_type,
            default_value=default_value,
            is_output=is_output,
            scope=VariableScope.PARAMETER,
        )


# ---------------------------------------------------------------------------
# Helper: split parameter list on commas respecting nesting
# ---------------------------------------------------------------------------


def _split_params(text: str) -> list[str]:
    """Split a parameter string on commas, respecting nested parentheses."""
    parts: list[str] = []
    current: list[str] = []
    depth = 0

    for ch in text:
        if ch == "(":
            depth += 1
            current.append(ch)
        elif ch == ")":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)

    if current:
        parts.append("".join(current).strip())

    return parts


# ---------------------------------------------------------------------------
# Top-level convenience function
# ---------------------------------------------------------------------------


def compile_sp(tsql_text: str, target_db: str) -> CompilationResult:
    """Compile a T-SQL stored procedure to the target dialect.

    Convenience function that creates an SPCompiler and runs the full pipeline.

    Args:
        tsql_text: T-SQL stored procedure source code.
        target_db: Target database type ("kingbasees" or "dm8").

    Returns:
        CompilationResult with generated code and diagnostics.

    Examples:
        >>> result = compile_sp(
        ...     "CREATE PROCEDURE get_count AS SELECT COUNT(*) FROM t",
        ...     "kingbasees"
        ... )
        >>> result.success
        True
        >>> "CREATE OR REPLACE FUNCTION" in result.generated_code
        True
    """
    compiler = SPCompiler(target_db=target_db)
    return compiler.compile(tsql_text)
