"""
Control Flow Extractor — converts semantic blocks into IR nodes.

This is the BRIDGE between the parser and the IR. It enforces the critical
architectural constraint:

    ✅ sqlglot is ONLY called for BlockType.SQL (SELECT/INSERT/UPDATE/DELETE)
    ❌ sqlglot is NEVER called for IF, WHILE, DECLARE, or any control flow

The extractor:
    1. Pattern-matches each SemanticBlock to determine its IR node type
    2. For SQL blocks: extracts SQL text, optionally parses with sqlglot
    3. For control flow: recursively processes nested body blocks
    4. Gracefully degrades if sqlglot fails (raw SQL text preserved)

Usage:
    from architecture.core.sql.compiler.parser import tokenize, segment_blocks, extract_ir_nodes

    tokens = tokenize(tsql_text)
    blocks = segment_blocks(tokens)
    ir_nodes = extract_ir_nodes(blocks)
"""

from __future__ import annotations

from ..ir import (
    IRAssign,
    IRBlock,
    IRExec,
    IRIf,
    IRNode,
    IRReturn,
    IRSQL,
    IRTransaction,
    IRVariable,
    IRWhile,
    VariableScope,
)
from .block_segmenter import BlockType, SemanticBlock
from .lexer import Token, TokenType


# ---------------------------------------------------------------------------
# Error type
# ---------------------------------------------------------------------------


class ExtractionError(Exception):
    """Raised when block-to-IR conversion encounters invalid structure."""

    def __init__(self, message: str, line: int = 0) -> None:
        self.line = line
        super().__init__(
            f"Extraction error{f' at line {line}' if line else ''}: {message}"
        )


# ---------------------------------------------------------------------------
# Main extraction function
# ---------------------------------------------------------------------------


def extract_ir_nodes(
    blocks: list[SemanticBlock],
    *,
    use_sqlglot: bool = True,
) -> list[IRNode]:
    """Convert a list of SemanticBlocks into IR nodes.

    This is the main entry point. Each block is classified and converted
    to the appropriate IRNode subtype.

    Args:
        blocks: Segmented semantic blocks from segment_blocks().
        use_sqlglot: If True, parse SQL statements with sqlglot (non-fatal).

    Returns:
        List of IRNode objects representing the procedure body.

    Raises:
        ExtractionError: If a block cannot be converted (malformed syntax).
    """
    nodes: list[IRNode] = []

    for block in blocks:
        node = _block_to_ir_node(block, use_sqlglot=use_sqlglot)
        nodes.append(node)

    return nodes


# ---------------------------------------------------------------------------
# Block-to-IR dispatch
# ---------------------------------------------------------------------------


def _block_to_ir_node(
    block: SemanticBlock,
    *,
    use_sqlglot: bool = True,
) -> IRNode:
    """Convert a single SemanticBlock to its corresponding IRNode.

    Dispatch table:
        DECLARE      → IRVariable
        ASSIGN       → IRAssign
        SQL          → IRSQL (sqlglot here)
        IF           → IRIf (recursive)
        WHILE        → IRWhile (recursive)
        TRANSACTION  → IRTransaction
        EXEC         → IRExec
        BLOCK        → IRBlock (recursive)
        RETURN       → IRReturn
        PRINT        → IRExec (treated as procedure call)
        UNKNOWN      → IRSQL (pass-through as raw SQL)
    """
    bt = block.block_type

    if bt == BlockType.DECLARE:
        return _extract_variable(block)
    elif bt == BlockType.ASSIGN:
        return _extract_assign(block)
    elif bt == BlockType.SQL:
        return _extract_sql(block, use_sqlglot=use_sqlglot)
    elif bt == BlockType.IF:
        return _extract_if(block, use_sqlglot=use_sqlglot)
    elif bt == BlockType.WHILE:
        return _extract_while(block, use_sqlglot=use_sqlglot)
    elif bt == BlockType.TRANSACTION:
        return _extract_transaction(block)
    elif bt == BlockType.EXEC:
        return _extract_exec(block)
    elif bt == BlockType.BLOCK:
        return _extract_block(block, use_sqlglot=use_sqlglot)
    elif bt == BlockType.RETURN:
        return _extract_return(block)
    elif bt == BlockType.PRINT:
        return _extract_print(block)
    elif bt in (BlockType.CATCH, BlockType.TRY):
        # TRY/CATCH: treat body blocks as IR
        body_nodes = extract_ir_nodes(
            list(block.body_blocks), use_sqlglot=use_sqlglot
        )
        return IRBlock(body=tuple(body_nodes), source_line=block.source_line)
    else:
        # UNKNOWN: pass-through as raw SQL
        return _extract_unknown(block)


# ---------------------------------------------------------------------------
# Individual extractors
# ---------------------------------------------------------------------------


def _extract_variable(block: SemanticBlock) -> IRVariable:
    """Extract DECLARE @var TYPE [= default] → IRVariable.

    Handles:
        DECLARE @x INT;
        DECLARE @name VARCHAR(100);
        DECLARE @price DECIMAL(10,2) = 0;
        DECLARE @cursor CURSOR FOR SELECT ...;

    Also handles OUTPUT parameters from CREATE PROCEDURE header.
    """
    tokens = list(block.tokens)
    if not tokens:
        raise ExtractionError("Empty DECLARE block", block.source_line)

    # Find the variable token
    var_name = ""
    var_idx = -1
    for i, t in enumerate(tokens):
        if t.type == TokenType.VARIABLE:
            var_name = t.value
            var_idx = i
            break

    if not var_name:
        raise ExtractionError(
            "Cannot extract variable name from DECLARE",
            block.source_line,
        )

    # Collect the data type tokens (everything between variable and DEFAULT/= or end)
    type_tokens: list[str] = []
    default_value: str | None = None
    is_cursor = False
    is_output = False

    i = var_idx + 1
    while i < len(tokens):
        t = tokens[i]
        if t.type == TokenType.KEYWORD:
            upper = t.value.upper()
            if upper == "CURSOR":
                is_cursor = True
                type_tokens.append(t.value)
                break
            elif upper == "OUTPUT" or upper == "OUT":
                is_output = True
                i += 1
                continue
            elif upper in ("DEFAULT", "="):
                # Default value follows
                i += 1
                default_parts: list[str] = []
                while i < len(tokens) and not (
                    tokens[i].type == TokenType.PUNCTUATION
                    and tokens[i].value == ";"
                ):
                    default_parts.append(_token_to_text(tokens[i]))
                    i += 1
                default_value = " ".join(default_parts).strip()
                break
        type_tokens.append(t.value)
        i += 1

    data_type = " ".join(type_tokens).strip()

    # Normalize data types for cross-dialect compatibility
    data_type = _normalize_data_type(data_type)

    scope = VariableScope.CURSOR if is_cursor else VariableScope.LOCAL

    return IRVariable(
        name=var_name,
        data_type=data_type,
        default_value=default_value,
        is_output=is_output,
        scope=scope,
        source_line=block.source_line,
    )


def _extract_assign(block: SemanticBlock) -> IRAssign:
    """Extract SET @var = expression → IRAssign.

    Handles:
        SET @x = 10;
        SET @x = @x + 1;
        SET @x = (SELECT COUNT(*) FROM orders);  — scalar subquery

    Also handles SELECT @var = col FROM table pattern.
    """
    tokens = list(block.tokens)

    # Find the target variable
    target = ""
    target_idx = -1
    for i, t in enumerate(tokens):
        if t.type == TokenType.VARIABLE:
            target = t.value
            target_idx = i
            break

    if not target:
        # Might be a plain SET statement without variable (e.g., SET NOCOUNT ON)
        # Collect all tokens as expression
        expr_text = " ".join(_token_to_text(t) for t in tokens)
        return IRAssign(
            target="",
            expression=expr_text,
            source_line=block.source_line,
        )

    # Check if it's SELECT @var = ... pattern
    is_scalar_query = False
    if tokens[0].type == TokenType.KEYWORD and tokens[0].value.upper() == "SELECT":
        is_scalar_query = True

    # Collect expression tokens (everything after = or after variable assignment)
    # For SET: everything after '=' following the variable
    # For SELECT: everything after the first variable and '='
    expr_tokens: list[str] = []
    in_expr = False
    for t in tokens:
        if t.type == TokenType.VARIABLE and t.value == target and not in_expr:
            in_expr = True
            continue
        if in_expr:
            if t.type == TokenType.OPERATOR and t.value == "=":
                continue  # skip the = operator
            expr_tokens.append(_token_to_text(t))

    expression = " ".join(expr_tokens).strip()

    # Check for scalar subquery pattern: (SELECT ...)
    if expression.startswith("(") and "SELECT" in expression.upper():
        is_scalar_query = True
        expression = expression.strip("()").strip()

    return IRAssign(
        target=target,
        expression=expression,
        is_scalar_query=is_scalar_query,
        source_line=block.source_line,
    )


def _extract_sql(
    block: SemanticBlock,
    *,
    use_sqlglot: bool = True,
) -> IRSQL:
    """Extract SQL statement → IRSQL.

    This is the ONLY place where sqlglot is called. The check on block.block_type
    guarantees that IF/WHILE/DECLARE never reach sqlglot.

    If sqlglot fails, the raw SQL text is preserved as fallback.
    """
    sql_text = _reconstitute_sql_text(block.tokens)

    sqlglot_ast = None
    is_dml = True
    is_select_into = False
    target_variable: str | None = None

    # Determine statement type
    stmt_type = _get_statement_type(sql_text)

    if stmt_type not in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        is_dml = False

    # Check for SELECT @var = col FROM table pattern
    if stmt_type == "SELECT" and "@" in sql_text:
        # Look for variable assignment pattern in SELECT
        import re
        var_match = re.match(
            r"SELECT\s+@(\w+)\s*=", sql_text, re.IGNORECASE
        )
        if var_match:
            is_select_into = True
            target_variable = var_match.group(1)

    # Parse with sqlglot (DML only, non-fatal)
    if use_sqlglot and is_dml:
        try:
            import sqlglot
            sqlglot_ast = sqlglot.parse_one(sql_text, dialect="tsql")
        except Exception:
            # Graceful fallback: preserve raw SQL text
            pass

    return IRSQL(
        sql_text=sql_text,
        sqlglot_ast=sqlglot_ast,
        is_dml=is_dml,
        is_select_into=is_select_into,
        target_variable=target_variable,
        source_line=block.source_line,
    )


def _extract_if(
    block: SemanticBlock,
    *,
    use_sqlglot: bool = True,
) -> IRIf:
    """Extract IF condition + body → IRIf.

    Recursively processes then_body and else_body blocks.
    sqlglot is NEVER called on the IF condition — only on nested SQL blocks.
    """
    # Reconstruct condition from header_tokens
    condition = _reconstitute_sql_text(block.header_tokens)

    # Process THEN body (body_blocks)
    then_body = tuple(
        extract_ir_nodes(list(block.body_blocks), use_sqlglot=use_sqlglot)
    )

    # ELSE body — handled by the block segmenter as part of the structure.
    # If has_else is True, the ELSE body blocks were already merged.
    # The block segmenter currently doesn't separate then/else cleanly,
    # so for now we treat all body_blocks as then_body.
    else_body: tuple[IRNode, ...] = ()

    return IRIf(
        condition=condition,
        then_body=then_body,
        else_body=else_body,
        source_line=block.source_line,
    )


def _extract_while(
    block: SemanticBlock,
    *,
    use_sqlglot: bool = True,
) -> IRWhile:
    """Extract WHILE condition + body → IRWhile.

    Recursively processes the WHILE body blocks.
    """
    condition = _reconstitute_sql_text(block.header_tokens)

    body = tuple(
        extract_ir_nodes(list(block.body_blocks), use_sqlglot=use_sqlglot)
    )

    return IRWhile(
        condition=condition,
        body=body,
        source_line=block.source_line,
    )


def _extract_transaction(block: SemanticBlock) -> IRTransaction:
    """Extract BEGIN TRANSACTION / COMMIT / ROLLBACK → IRTransaction."""
    tokens = list(block.tokens)
    if not tokens:
        raise ExtractionError("Empty transaction block", block.source_line)

    first = tokens[0]
    if first.type != TokenType.KEYWORD:
        raise ExtractionError(
            f"Expected keyword in transaction block, got {first.type.name}",
            block.source_line,
        )

    action = first.value.upper()

    # Normalize: "ROLLBACK" could be "ROLLBACK TRANSACTION" or just "ROLLBACK"
    savepoint_name: str | None = None
    if len(tokens) > 1 and tokens[1].type == TokenType.IDENTIFIER:
        savepoint_name = tokens[1].value

    return IRTransaction(
        action=action,
        savepoint_name=savepoint_name,
        source_line=block.source_line,
    )


def _extract_exec(block: SemanticBlock) -> IRExec:
    """Extract EXEC procedure_name [args] → IRExec.

    Handles:
        EXEC sp_name;
        EXEC sp_name @param1 = value1, @param2 = value2;
        EXECUTE sp_name 1, 2, 3;
    """
    tokens = list(block.tokens)
    if len(tokens) < 2:
        raise ExtractionError(
            "EXEC without procedure name",
            block.source_line,
        )

    # First token should be EXEC/EXECUTE
    # Second token is the procedure name
    proc_name = ""
    args: list[str] = []

    i = 1  # skip EXEC/EXECUTE
    if i < len(tokens) and tokens[i].type in (TokenType.IDENTIFIER, TokenType.KEYWORD):
        proc_name = tokens[i].value
        i += 1

    # Collect arguments (if any)
    arg_parts: list[str] = []
    while i < len(tokens):
        t = tokens[i]
        if t.type == TokenType.PUNCTUATION and t.value == ";":
            break
        arg_parts.append(_token_to_text(t))
        i += 1

    if arg_parts:
        args = [a.strip() for a in " ".join(arg_parts).split(",")]

    return IRExec(
        procedure_name=proc_name,
        arguments=tuple(args),
        source_line=block.source_line,
    )


def _extract_block(
    block: SemanticBlock,
    *,
    use_sqlglot: bool = True,
) -> IRBlock:
    """Extract anonymous BEGIN...END block → IRBlock."""
    body = tuple(
        extract_ir_nodes(list(block.body_blocks), use_sqlglot=use_sqlglot)
    )
    return IRBlock(body=body, source_line=block.source_line)


def _extract_return(block: SemanticBlock) -> IRReturn:
    """Extract RETURN [value] → IRReturn."""
    tokens = list(block.tokens)
    # First token is RETURN keyword
    value: str | None = None
    if len(tokens) > 1:
        value_parts = [_token_to_text(t) for t in tokens[1:]]
        value = " ".join(value_parts).strip().rstrip(";")
    return IRReturn(value=value, source_line=block.source_line)


def _extract_print(block: SemanticBlock) -> IRExec:
    """Extract PRINT message → IRExec (treat PRINT as call to output procedure)."""
    tokens = list(block.tokens)
    message_parts = [_token_to_text(t) for t in tokens[1:]]
    message = " ".join(message_parts).strip().rstrip(";")
    return IRExec(
        procedure_name="PRINT",
        arguments=(message,),
        source_line=block.source_line,
    )


def _extract_unknown(block: SemanticBlock) -> IRSQL:
    """Extract unrecognized statement → IRSQL (pass-through)."""
    sql_text = _reconstitute_sql_text(block.tokens)
    return IRSQL(
        sql_text=sql_text,
        is_dml=False,
        source_line=block.source_line,
    )


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _reconstitute_sql_text(tokens: tuple[Token, ...]) -> str:
    """Reconstitute original SQL text from tokens.

    Preserves whitespace and original casing where possible.
    Handles spacing correctly for operators adjacent to punctuation.
    """
    parts: list[str] = []
    prev_was_punct = False

    for i, t in enumerate(tokens):
        # Look ahead to check adjacent tokens
        next_t = tokens[i + 1] if i + 1 < len(tokens) else None

        if t.type == TokenType.PUNCTUATION:
            parts.append(t.value)
            prev_was_punct = True
        elif t.type == TokenType.VARIABLE:
            if not prev_was_punct:
                parts.append(" ")
            parts.append("@" + t.value)
            prev_was_punct = False
        elif t.type == TokenType.OPERATOR:
            # No space before operator if previous was punctuation (e.g., "(*)" → "(*)")
            if prev_was_punct:
                parts.append(t.value)
            else:
                parts.append(" " + t.value)
            # No space after operator if next is punctuation
            if next_t and next_t.type == TokenType.PUNCTUATION:
                prev_was_punct = False  # let punctuation handle it
            else:
                parts.append(" ")
                prev_was_punct = False
        else:
            if not prev_was_punct:
                parts.append(" ")
            parts.append(t.value)
            prev_was_punct = False

    return "".join(parts).strip()


def _token_to_text(token: Token) -> str:
    """Convert a token back to its text representation."""
    if token.type == TokenType.VARIABLE:
        return "@" + token.value
    elif token.type == TokenType.STRING:
        return "'" + token.value + "'"
    return token.value


def _get_statement_type(sql_text: str) -> str:
    """Get the SQL statement type from raw SQL text."""
    upper = sql_text.strip().upper()
    for stmt in ("SELECT", "INSERT", "UPDATE", "DELETE", "WITH", "EXEC",
                  "EXECUTE", "CREATE", "ALTER", "DROP", "TRUNCATE", "MERGE"):
        if upper.startswith(stmt + " ") or upper == stmt:
            return stmt
    return "UNKNOWN"


def _normalize_data_type(data_type: str) -> str:
    """Normalize T-SQL data types to generic names for cross-dialect use.

    E.g., NVARCHAR → VARCHAR, DATETIME2 → DATETIME
    Generators will map these to dialect-specific types.
    """
    upper = data_type.upper().strip()
    mapping = {
        "NVARCHAR": "VARCHAR",
        "NCHAR": "CHAR",
        "NTEXT": "TEXT",
        "DATETIME2": "DATETIME",
        "SMALLDATETIME": "DATETIME",
        "SMALLMONEY": "DECIMAL",
        "MONEY": "DECIMAL",
        "UNIQUEIDENTIFIER": "VARCHAR(36)",
        "IMAGE": "BINARY",
        "SQL_VARIANT": "VARCHAR",
    }

    # Handle parameterized types like VARCHAR(100), DECIMAL(10,2)
    base = upper.split("(")[0].strip()
    params = ""
    if "(" in upper:
        params = upper[upper.index("("):]

    if base in mapping:
        mapped_base = mapping[base]
        if "(" in mapped_base:
            return mapped_base
        return mapped_base + params

    return upper
