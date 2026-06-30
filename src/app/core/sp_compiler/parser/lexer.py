"""
T-SQL Lexer / Tokenizer — converts T-SQL stored procedure text into a token stream.

Handles:
    - Keyword recognition and normalization
    - @variable stripping (normalized to plain identifiers)
    - String literals with '' escaping
    - Line comments (--) and block comments (/* */)
    - GO batch separator
    - Numbers (integer and decimal)

Design:
    - Character-by-character scanner with lookahead
    - Each token carries (type, value, line, column) for error reporting
    - LexerError raised on unclosed strings, unclosed comments, malformed numbers

Usage:
    from app.core.sp_compiler.parser.lexer import tokenize

    tokens = tokenize("DECLARE @x INT; SET @x = 10;")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto


# ---------------------------------------------------------------------------
# Token types
# ---------------------------------------------------------------------------


class TokenType(Enum):
    KEYWORD = auto()        # DECLARE, SET, SELECT, IF, WHILE, etc.
    IDENTIFIER = auto()     # table names, column names, procedure names
    VARIABLE = auto()       # @var → value is normalized (no @ prefix)
    STRING = auto()         # 'string literal'
    NUMBER = auto()         # 123, 45.67
    OPERATOR = auto()       # =, <>, <, >, +, -, *, /
    PUNCTUATION = auto()    # , ; ( ) .
    COMMENT_LINE = auto()   # -- comment
    COMMENT_BLOCK = auto()  # /* comment */
    GO = auto()             # GO batch separator
    EOF = auto()            # End of input


# ---------------------------------------------------------------------------
# Token dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Token:
    """A single lexical token with source position.

    Attributes:
        type: The token type classification.
        value: The token's text value (normalized for variables).
        line: 1-based line number in the source.
        column: 1-based column number in the source.
    """
    type: TokenType
    value: str
    line: int = 1
    column: int = 1


# ---------------------------------------------------------------------------
# Error type
# ---------------------------------------------------------------------------


class LexerError(Exception):
    """Raised when the lexer encounters invalid input."""

    def __init__(self, message: str, line: int, column: int) -> None:
        self.message = message
        self.line = line
        self.column = column
        super().__init__(f"Lexer error at line {line}, col {column}: {message}")


# ---------------------------------------------------------------------------
# Keyword set
# ---------------------------------------------------------------------------

_KEYWORDS: set[str] = {
    # DML / DDL
    "SELECT", "INSERT", "UPDATE", "DELETE", "FROM", "WHERE", "JOIN",
    "LEFT", "RIGHT", "INNER", "OUTER", "ON", "AND", "OR", "NOT",
    "IN", "IS", "NULL", "EXISTS", "BETWEEN", "LIKE", "CASE",
    "WHEN", "THEN", "ELSE", "END", "DISTINCT", "ALL", "ANY", "SOME",
    "GROUP", "BY", "HAVING", "ORDER", "ASC", "DESC", "OFFSET",
    "FETCH", "FIRST", "NEXT", "ROWS", "ONLY", "UNION", "INTERSECT",
    "EXCEPT", "INTO", "VALUES", "SET", "DEFAULT", "PRIMARY", "KEY",
    "FOREIGN", "REFERENCES", "TABLE", "INDEX", "VIEW", "CREATE",
    "ALTER", "DROP", "ADD", "COLUMN", "CONSTRAINT", "UNIQUE",
    "CHECK", "CASCADE", "NO", "ACTION",
    # T-SQL specific
    "TOP", "PERCENT", "CROSS", "APPLY", "OUTER", "PIVOT", "UNPIVOT",
    "MERGE", "OUTPUT", "WITH", "NOLOCK", "READUNCOMMITTED",
    "READCOMMITTED", "REPEATABLEREAD", "SERIALIZABLE", "ROWLOCK",
    "PAGLOCK", "TABLOCK", "HOLDLOCK", "UPDLOCK", "XLOCK",
    "SCHEMABINDING", "ENCRYPTION", "RECOMPILE", "EXECUTE",
    # Procedural
    "DECLARE", "BEGIN", "TRANSACTION", "COMMIT", "ROLLBACK",
    "RETURN", "EXEC", "PRINT", "RAISERROR", "THROW",
    "TRY", "CATCH", "GOTO", "WAITFOR", "DELAY", "TIME",
    "CONTINUE", "BREAK", "WHILE", "IF",
    # Control
    "AS", "NOCOUNT", "ON", "OFF", "IDENTITY_INSERT",
    # Types
    "INT", "BIGINT", "SMALLINT", "TINYINT", "BIT",
    "VARCHAR", "NVARCHAR", "CHAR", "NCHAR", "TEXT", "NTEXT",
    "DECIMAL", "NUMERIC", "FLOAT", "REAL", "MONEY", "SMALLMONEY",
    "DATETIME", "DATETIME2", "SMALLDATETIME", "DATE", "TIME",
    "DATETIMEOFFSET", "TIMESTAMP", "UNIQUEIDENTIFIER",
    "IMAGE", "BINARY", "VARBINARY", "SQL_VARIANT", "XML",
    "TABLE", "CURSOR",
}

# Normalized keyword lookup (case-insensitive)
_KEYWORD_LOOKUP: dict[str, str] = {k.upper(): k.upper() for k in _KEYWORDS}


def _is_keyword(word: str) -> bool:
    """Check if a word is a recognized T-SQL keyword (case-insensitive)."""
    return word.upper() in _KEYWORD_LOOKUP


# ---------------------------------------------------------------------------
# Character classification helpers
# ---------------------------------------------------------------------------


def _is_whitespace(ch: str) -> bool:
    return ch in " \t\r\n"


def _is_alpha(ch: str) -> bool:
    return ("a" <= ch <= "z") or ("A" <= ch <= "Z") or ch == "_"


def _is_digit(ch: str) -> bool:
    return "0" <= ch <= "9"


def _is_alphanumeric(ch: str) -> bool:
    return _is_alpha(ch) or _is_digit(ch)


def _is_operator_start(ch: str) -> bool:
    return ch in "=<>!+-*/%^&|~"


def _is_punctuation(ch: str) -> bool:
    return ch in ",;().:"


# ---------------------------------------------------------------------------
# Main tokenize function
# ---------------------------------------------------------------------------


def tokenize(text: str, *, skip_comments: bool = True) -> list[Token]:
    """Tokenize T-SQL stored procedure text into a list of Token objects.

    Args:
        text: Raw T-SQL source text.
        skip_comments: If True (default), comment tokens are excluded from output.

    Returns:
        List of Token objects. Always ends with a TokenType.EOF token.

    Raises:
        LexerError: On unclosed string literal, unclosed block comment,
                    or malformed number.

    Examples:
        >>> tokenize("DECLARE @x INT;")
        [Token(KEYWORD,'DECLARE',1,1), Token(VARIABLE,'x',1,9), ...]

        >>> tokenize("SET @name = 'O''Brien';")
        # Variable 'name', operator '=', string "O'Brien"
    """
    tokens: list[Token] = []
    pos = 0
    line = 1
    col = 1
    length = len(text)

    def _peek(offset: int = 0) -> str:
        """Look ahead without consuming."""
        idx = pos + offset
        if idx < length:
            return text[idx]
        return ""

    def _advance(count: int = 1) -> None:
        nonlocal pos, col, line
        for _ in range(count):
            if pos < length:
                ch = text[pos]
                if ch == "\n":
                    line += 1
                    col = 1
                else:
                    col += 1
                pos += 1

    def _make_token(ttype: TokenType, value: str, tk_line: int, tk_col: int) -> Token:
        return Token(type=ttype, value=value, line=tk_line, column=tk_col)

    def _scan_string(delimiter: str = "'") -> Token:
        """Scan a single-quoted string literal, handling '' escape."""
        tk_line, tk_col = line, col
        _advance()  # consume opening quote
        value_chars: list[str] = []
        while pos < length:
            ch = _peek()
            if ch == delimiter:
                # Check for escaped quote (doubled delimiter)
                if _peek(1) == delimiter:
                    value_chars.append(delimiter)
                    _advance(2)
                    continue
                else:
                    _advance()  # consume closing quote
                    break
            elif ch == "\n":
                # Unclosed string at end of line — error
                raise LexerError(
                    f"Unclosed string literal (missing closing {delimiter})",
                    tk_line, tk_col
                )
            else:
                value_chars.append(ch)
                _advance()
        else:
            # Reached EOF before closing quote
            raise LexerError(
                f"Unclosed string literal (missing closing {delimiter})",
                tk_line, tk_col
            )
        return _make_token(TokenType.STRING, "".join(value_chars), tk_line, tk_col)

    def _scan_line_comment() -> Token:
        """Scan -- line comment to end of line."""
        tk_line, tk_col = line, col
        _advance(2)  # consume --
        value_chars: list[str] = []
        while pos < length and _peek() != "\n":
            value_chars.append(_peek())
            _advance()
        return _make_token(TokenType.COMMENT_LINE, "".join(value_chars), tk_line, tk_col)

    def _scan_block_comment() -> Token:
        """Scan /* block comment */ handling nesting."""
        tk_line, tk_col = line, col
        _advance(2)  # consume /*
        depth = 1
        value_chars: list[str] = []
        while pos < length and depth > 0:
            if _peek() == "/" and _peek(1) == "*":
                depth += 1
                value_chars.extend("/*")
                _advance(2)
            elif _peek() == "*" and _peek(1) == "/":
                depth -= 1
                if depth > 0:
                    value_chars.extend("*/")
                _advance(2)
            elif _peek() == "\n":
                value_chars.append("\n")
                _advance()
            else:
                value_chars.append(_peek())
                _advance()
        if depth > 0:
            raise LexerError(
                "Unclosed block comment (missing */)",
                tk_line, tk_col
            )
        return _make_token(TokenType.COMMENT_BLOCK, "".join(value_chars), tk_line, tk_col)

    def _scan_number() -> Token:
        """Scan an integer or decimal number."""
        tk_line, tk_col = line, col
        value_chars: list[str] = []
        has_decimal = False
        while pos < length and _is_digit(_peek()):
            value_chars.append(_peek())
            _advance()
        if _peek() == "." and _is_digit(_peek(1)):
            has_decimal = True
            value_chars.append(".")
            _advance()
            while pos < length and _is_digit(_peek()):
                value_chars.append(_peek())
                _advance()
        # Check for malformed number like "12.34.56"
        if _peek() == "." and has_decimal:
            raise LexerError(
                f"Malformed number: multiple decimal points in '{''.join(value_chars)}.'",
                tk_line, tk_col
            )
        return _make_token(TokenType.NUMBER, "".join(value_chars), tk_line, tk_col)

    def _scan_variable() -> Token:
        """Scan @variable — normalize by stripping @ prefix."""
        tk_line, tk_col = line, col
        _advance()  # consume @
        if pos >= length or not (_is_alpha(_peek()) or _peek() == "@"):
            # @@ system variables like @@IDENTITY, @@ROWCOUNT
            if _peek() == "@":
                _advance()
                var_chars: list[str] = []
                while pos < length and _is_alphanumeric(_peek()):
                    var_chars.append(_peek())
                    _advance()
                # Keep @@ prefix for system variables
                return _make_token(TokenType.VARIABLE, "@@" + "".join(var_chars), tk_line, tk_col)
            return _make_token(TokenType.VARIABLE, "", tk_line, tk_col)

        var_chars: list[str] = []
        while pos < length and _is_alphanumeric(_peek()):
            var_chars.append(_peek())
            _advance()
        return _make_token(TokenType.VARIABLE, "".join(var_chars), tk_line, tk_col)

    def _scan_word_or_keyword() -> Token:
        """Scan an identifier or keyword."""
        tk_line, tk_col = line, col
        value_chars: list[str] = []
        while pos < length and _is_alphanumeric(_peek()):
            value_chars.append(_peek())
            _advance()
        raw = "".join(value_chars)
        upper = raw.upper()

        # Check for GO as standalone batch separator
        if upper == "GO" and (pos >= length or _is_whitespace(_peek()) or _peek() == "\n"):
            # Consume trailing whitespace after GO
            while pos < length and _is_whitespace(_peek()) and _peek() != "\n":
                _advance()
            return _make_token(TokenType.GO, "GO", tk_line, tk_col)

        if _is_keyword(raw):
            return _make_token(TokenType.KEYWORD, upper, tk_line, tk_col)

        return _make_token(TokenType.IDENTIFIER, raw, tk_line, tk_col)

    def _scan_operator() -> Token:
        """Scan operator tokens."""
        tk_line, tk_col = line, col
        ch = _peek()
        # Two-character operators
        if ch == "<" and _peek(1) == ">":
            _advance(2)
            return _make_token(TokenType.OPERATOR, "<>", tk_line, tk_col)
        if ch == "<" and _peek(1) == "=":
            _advance(2)
            return _make_token(TokenType.OPERATOR, "<=", tk_line, tk_col)
        if ch == ">" and _peek(1) == "=":
            _advance(2)
            return _make_token(TokenType.OPERATOR, ">=", tk_line, tk_col)
        if ch == "!" and _peek(1) == "=":
            _advance(2)
            return _make_token(TokenType.OPERATOR, "!=", tk_line, tk_col)
        if (ch == "+" or ch == "-" or ch == "*" or ch == "/") and _peek(1) == "=":
            op = ch
            _advance(2)
            return _make_token(TokenType.OPERATOR, op + "=", tk_line, tk_col)
        # Single-character operators (skip * and / which could open comments)
        if ch == "=":
            _advance()
            return _make_token(TokenType.OPERATOR, "=", tk_line, tk_col)
        _advance()
        return _make_token(TokenType.OPERATOR, ch, tk_line, tk_col)

    # ---- Main scan loop ----
    while pos < length:
        ch = _peek()

        # Whitespace
        if _is_whitespace(ch):
            _advance()
            continue

        # Line comment
        if ch == "-" and _peek(1) == "-":
            token = _scan_line_comment()
            if not skip_comments:
                tokens.append(token)
            continue

        # Block comment
        if ch == "/" and _peek(1) == "*":
            token = _scan_block_comment()
            if not skip_comments:
                tokens.append(token)
            continue

        # String literal
        if ch == "'":
            tokens.append(_scan_string("'"))
            continue

        # Variable
        if ch == "@":
            tokens.append(_scan_variable())
            continue

        # Number
        if _is_digit(ch):
            tokens.append(_scan_number())
            continue

        # Identifier or keyword
        if _is_alpha(ch):
            tokens.append(_scan_word_or_keyword())
            continue

        # Punctuation
        if _is_punctuation(ch):
            tk_line, tk_col = line, col
            _advance()
            tokens.append(_make_token(TokenType.PUNCTUATION, ch, tk_line, tk_col))
            continue

        # Operators (must check after comments since / and * could start comments)
        if _is_operator_start(ch):
            # Don't match * or / alone as operators — they've already been
            # handled above if they started comments
            if ch in "*/":
                tk_line, tk_col = line, col
                _advance()
                tokens.append(_make_token(TokenType.OPERATOR, ch, tk_line, tk_col))
                continue
            tokens.append(_scan_operator())
            continue

        # Brackets for quoted identifiers
        if ch == "[":
            tk_line, tk_col = line, col
            _advance()
            bracket_chars: list[str] = []
            while pos < length and _peek() != "]":
                if _peek() == "\n":
                    raise LexerError(
                        "Unclosed bracket identifier (missing ])",
                        tk_line, tk_col
                    )
                bracket_chars.append(_peek())
                _advance()
            if pos < length:
                _advance()  # consume ]
            tokens.append(_make_token(TokenType.IDENTIFIER, "".join(bracket_chars), tk_line, tk_col))
            continue

        # Unknown character
        raise LexerError(
            f"Unexpected character: '{ch}' (U+{ord(ch):04X})",
            line, col
        )

    # End of input
    tokens.append(_make_token(TokenType.EOF, "", line, col))
    return tokens


# ---------------------------------------------------------------------------
# Convenience: split on GO for multi-batch procedures
# ---------------------------------------------------------------------------


def split_batches(tokens: list[Token]) -> list[list[Token]]:
    """Split a token list on GO tokens into separate batches.

    Each batch is a list of tokens (excluding the GO separator and trailing EOF).
    This is useful for procedures that use GO as a statement separator.

    Args:
        tokens: Token list from tokenize().

    Returns:
        List of token batches. Empty list if input was only EOF.
    """
    batches: list[list[Token]] = []
    current: list[Token] = []

    for token in tokens:
        if token.type == TokenType.GO:
            if current:
                batches.append(current)
                current = []
        elif token.type == TokenType.EOF:
            if current:
                batches.append(current)
        else:
            current.append(token)

    return batches
