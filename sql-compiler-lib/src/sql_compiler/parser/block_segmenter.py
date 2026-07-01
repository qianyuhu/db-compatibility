"""
Block Segmentation Engine — converts token stream into semantic blocks.

Two-pass algorithm:
    Pass 1: Flat token grouping — split token stream into statement-level blocks
            at block boundary keywords (IF, WHILE, BEGIN, END, etc.)
    Pass 2: Tree building — stack-based depth tracking with IF/WHILE context
            absorption to build a nested block tree.

Usage:
    from sql_compiler.parser import tokenize, segment_blocks
    tokens = tokenize(tsql_text)
    blocks = segment_blocks(tokens)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto

from .lexer import Token, TokenType


# ---------------------------------------------------------------------------
# Block types
# ---------------------------------------------------------------------------


class BlockType(Enum):
    DECLARE = auto()
    ASSIGN = auto()
    SQL = auto()
    IF = auto()
    ELSE = auto()
    WHILE = auto()
    TRANSACTION = auto()
    EXEC = auto()
    BLOCK = auto()
    RETURN = auto()
    PRINT = auto()
    TRY = auto()
    CATCH = auto()
    UNKNOWN = auto()


# ---------------------------------------------------------------------------
# SemanticBlock
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SemanticBlock:
    block_type: BlockType
    tokens: tuple[Token, ...] = field(default_factory=tuple)
    header_tokens: tuple[Token, ...] = field(default_factory=tuple)
    body_blocks: tuple[SemanticBlock, ...] = field(default_factory=tuple)
    has_else: bool = False
    source_line: int = 0


# ---------------------------------------------------------------------------
# Error
# ---------------------------------------------------------------------------


class SegmentationError(Exception):
    def __init__(self, message: str, line: int = 0) -> None:
        self.line = line
        loc = f" at line {line}" if line else ""
        super().__init__(f"Segmentation error{loc}: {message}")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def segment_blocks(tokens: list[Token]) -> list[SemanticBlock]:
    tokens = [t for t in tokens if t.type != TokenType.EOF]
    if not tokens:
        return []
    return _Segmenter(tokens).run()


# ---------------------------------------------------------------------------
# Block-start keyword sets
# ---------------------------------------------------------------------------

_SQL_STARTERS = {"SELECT", "INSERT", "UPDATE", "DELETE", "WITH", "MERGE", "TRUNCATE"}
_FLOW_STARTERS = {"IF", "WHILE", "BEGIN", "END", "ELSE", "RETURN",
                  "TRY", "CATCH", "GOTO", "BREAK", "CONTINUE"}


def _is_block_boundary(keyword: str) -> bool:
    return keyword in _SQL_STARTERS | _FLOW_STARTERS | {
        "DECLARE", "SET", "EXEC", "EXECUTE", "PRINT", "COMMIT", "ROLLBACK",
    }


# ---------------------------------------------------------------------------
# Token stream helper
# ---------------------------------------------------------------------------


class _TS:
    """Token stream with position tracking."""

    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.pos = 0

    @property
    def eof(self) -> bool:
        return self.pos >= len(self.tokens)

    def current(self) -> Token:
        if self.eof:
            return Token(TokenType.EOF, "", 0, 0)
        return self.tokens[self.pos]

    def peek(self, offset: int = 1) -> Token:
        idx = self.pos + offset
        if idx >= len(self.tokens):
            return Token(TokenType.EOF, "", 0, 0)
        return self.tokens[idx]

    def advance(self, n: int = 1) -> None:
        self.pos += n

    def keyword(self) -> str:
        t = self.current()
        if t.type == TokenType.KEYWORD:
            return t.value.upper()
        return ""

    def keyword_is(self, *kw: str) -> bool:
        return self.keyword() in {k.upper() for k in kw}

    def skip_semicolons(self) -> None:
        while not self.eof:
            t = self.current()
            if t.type == TokenType.PUNCTUATION and t.value == ";":
                self.advance()
            else:
                break

    def collect_until_semicolon(self, sql_context: bool = False) -> list[Token]:
        """Collect tokens: first token always collected, stop at ; or keyword boundary.
        
        Args:
            sql_context: If True, SET is not treated as a block boundary
                (needed for UPDATE ... SET ... and INSERT ... SET ... patterns).
        """
        collected: list[Token] = []
        if not self.eof:
            collected.append(self.current())
            self.advance()
        while not self.eof:
            t = self.current()
            if t.type == TokenType.PUNCTUATION and t.value == ";":
                self.advance()
                break
            if t.type == TokenType.KEYWORD:
                kw = t.value.upper()
                # In SQL context, SET is a clause keyword (UPDATE...SET), not a boundary
                if sql_context and kw == "SET":
                    collected.append(t)
                    self.advance()
                    continue
                if _is_block_boundary(kw):
                    break
            collected.append(t)
            self.advance()
        return collected

    def collect_until_keyword(self, *keywords: str) -> list[Token]:
        """Collect tokens until one of the given keywords (keyword consumed)."""
        collected: list[Token] = []
        while not self.eof:
            t = self.current()
            if t.type == TokenType.KEYWORD and t.value.upper() in {k.upper() for k in keywords}:
                self.advance()
                break
            collected.append(t)
            self.advance()
        return collected


# ---------------------------------------------------------------------------
# Segmenter
# ---------------------------------------------------------------------------


class _Segmenter:

    MAX_DEPTH = 64

    def __init__(self, tokens: list[Token]) -> None:
        self.ts = _TS(tokens)

    def run(self) -> list[SemanticBlock]:
        # Pass 1: Flat blocks
        flat = self._pass1()
        # Pass 2: Build tree
        return self._pass2(flat)

    # ------------------------------------------------------------------
    # Pass 1: Flat token grouping
    # ------------------------------------------------------------------

    def _pass1(self) -> list[SemanticBlock]:
        blocks: list[SemanticBlock] = []

        while not self.ts.eof:
            self.ts.skip_semicolons()
            if self.ts.eof:
                break

            kw = self.ts.keyword()
            token = self.ts.current()

            if kw == "BEGIN":
                nxt = self.ts.peek(1).value.upper()
                if nxt in ("TRAN", "TRANSACTION"):
                    blocks.append(SemanticBlock(
                        BlockType.TRANSACTION, (token,), source_line=token.line))
                    self.ts.advance(2)
                elif nxt == "TRY":
                    blocks.append(SemanticBlock(
                        BlockType.TRY, (token, self.ts.peek(1)), source_line=token.line))
                    self.ts.advance(2)
                elif nxt == "CATCH":
                    blocks.append(SemanticBlock(
                        BlockType.CATCH, (token, self.ts.peek(1)), source_line=token.line))
                    self.ts.advance(2)
                else:
                    blocks.append(SemanticBlock(
                        BlockType.BLOCK, (token,), source_line=token.line))
                    self.ts.advance()

            elif kw == "END":
                blocks.append(SemanticBlock(
                    BlockType.BLOCK, (token,), source_line=token.line))
                self.ts.advance()
                if self.ts.keyword_is("IF", "WHILE", "CATCH", "LOOP"):
                    self.ts.advance()

            elif kw == "IF":
                self.ts.advance()
                # Collect condition tokens until THEN (don't consume THEN/BEGIN)
                cond: list[Token] = []
                while not self.ts.eof:
                    t = self.ts.current()
                    if t.type == TokenType.KEYWORD and t.value.upper() in ("THEN", "BEGIN"):
                        # Don't consume — let the main loop pick up BEGIN/THEN
                        break
                    cond.append(t)
                    self.ts.advance()
                # Skip THEN if present (THEN is not a block boundary keyword)
                if self.ts.keyword_is("THEN"):
                    self.ts.advance()
                blocks.append(SemanticBlock(
                    BlockType.IF, header_tokens=tuple(cond), source_line=token.line))

            elif kw == "ELSE":
                blocks.append(SemanticBlock(
                    BlockType.ELSE, (token,), source_line=token.line))
                self.ts.advance()

            elif kw == "WHILE":
                self.ts.advance()
                cond = []
                while not self.ts.eof:
                    t = self.ts.current()
                    if t.type == TokenType.KEYWORD and t.value.upper() in ("BEGIN", "LOOP"):
                        break  # Don't consume
                    cond.append(t)
                    self.ts.advance()
                blocks.append(SemanticBlock(
                    BlockType.WHILE, header_tokens=tuple(cond), source_line=token.line))

            elif kw == "DECLARE":
                blocks.append(SemanticBlock(
                    BlockType.DECLARE, tokens=tuple(self.ts.collect_until_semicolon()),
                    source_line=token.line))

            elif kw == "SET":
                blocks.append(SemanticBlock(
                    BlockType.ASSIGN, tokens=tuple(self.ts.collect_until_semicolon()),
                    source_line=token.line))

            elif kw in _SQL_STARTERS:
                blocks.append(SemanticBlock(
                    BlockType.SQL, tokens=tuple(self.ts.collect_until_semicolon(sql_context=True)),
                    source_line=token.line))

            elif kw in ("EXEC", "EXECUTE"):
                blocks.append(SemanticBlock(
                    BlockType.EXEC, tokens=tuple(self.ts.collect_until_semicolon()),
                    source_line=token.line))

            elif kw == "RETURN":
                blocks.append(SemanticBlock(
                    BlockType.RETURN, tokens=tuple(self.ts.collect_until_semicolon()),
                    source_line=token.line))

            elif kw == "PRINT":
                blocks.append(SemanticBlock(
                    BlockType.PRINT, tokens=tuple(self.ts.collect_until_semicolon()),
                    source_line=token.line))

            elif kw in ("COMMIT", "ROLLBACK"):
                blocks.append(SemanticBlock(
                    BlockType.TRANSACTION, (token,), source_line=token.line))
                self.ts.advance()

            else:
                blocks.append(SemanticBlock(
                    BlockType.UNKNOWN, tokens=tuple(self.ts.collect_until_semicolon()),
                    source_line=token.line))

        return blocks

    # ------------------------------------------------------------------
    # Pass 2: Tree building via stack
    # ------------------------------------------------------------------

    def _pass2(self, flat: list[SemanticBlock]) -> list[SemanticBlock]:
        """Build nested tree using a scope stack.

        The stack tracks open scopes: IF, WHILE, and anonymous BEGIN blocks.
        When we see BEGIN, we push a scope.  When we see END, we pop a scope
        and attach all accumulated children.  IF/WHILE capture their condition
        first, then their body is the scope that follows.

        Edge cases handled:
        - IF with single-statement body (no BEGIN/END)
        - IF with compound body (BEGIN...END)
        - ELSE attaches to the most recent IF
        - Nested WHILE inside IF (and vice versa)
        - Outer BEGIN...END (procedure body wrapper)
        """
        # The root is a virtual BLOCK that collects top-level blocks
        root = SemanticBlock(BlockType.BLOCK, source_line=0)
        scope_stack: list[SemanticBlock] = [root]
        current_scope: list[SemanticBlock] = []  # children being accumulated
        pending_if: SemanticBlock | None = None  # IF waiting for body
        pending_while: SemanticBlock | None = None  # WHILE waiting for body
        pending_else_body: list[SemanticBlock] | None = None  # ELSE body accumulator

        def _finish_pending() -> None:
            """Flush any pending IF/WHILE/ELSE into the current scope."""
            nonlocal pending_if, pending_while, pending_else_body
            if pending_else_body is not None:
                # Attach ELSE body to the last IF in current_scope
                if current_scope and current_scope[-1].block_type == BlockType.IF:
                    if_block = current_scope[-1]
                    current_scope[-1] = SemanticBlock(
                        BlockType.IF,
                        header_tokens=if_block.header_tokens,
                        body_blocks=if_block.body_blocks,
                        has_else=True,
                        source_line=if_block.source_line,
                    )
                    # Append ELSE body as separate block (will be processed by extractor)
                    current_scope.append(SemanticBlock(
                        BlockType.ELSE,
                        body_blocks=tuple(pending_else_body),
                        source_line=if_block.source_line,
                    ))
                pending_else_body = None

        for block in flat:
            bt = block.block_type

            if bt == BlockType.BLOCK:
                first_val = block.tokens[0].value.upper() if block.tokens else ""
                if first_val == "BEGIN":
                    # Push a new scope
                    new_scope = SemanticBlock(BlockType.BLOCK, source_line=block.source_line)
                    # Attach pending IF/WHILE context to this scope
                    if pending_if is not None:
                        new_scope = SemanticBlock(
                            BlockType.IF,
                            header_tokens=pending_if.header_tokens,
                            source_line=pending_if.source_line,
                        )
                        pending_if = None
                    elif pending_while is not None:
                        new_scope = SemanticBlock(
                            BlockType.WHILE,
                            header_tokens=pending_while.header_tokens,
                            source_line=pending_while.source_line,
                        )
                        pending_while = None

                    scope_stack.append(new_scope)
                    current_scope.append(new_scope)
                    current_scope = []  # start fresh for the new scope
                else:
                    # END — close current scope
                    _finish_pending()
                    if len(scope_stack) <= 1:
                        raise SegmentationError(
                            "Unmatched END", block.source_line)

                    # Pop the current scope
                    scope = scope_stack.pop()
                    # Set its body_blocks
                    if scope.block_type == BlockType.IF:
                        scope = SemanticBlock(
                            BlockType.IF,
                            header_tokens=scope.header_tokens,
                            body_blocks=tuple(current_scope),
                            source_line=scope.source_line,
                        )
                    elif scope.block_type == BlockType.WHILE:
                        scope = SemanticBlock(
                            BlockType.WHILE,
                            header_tokens=scope.header_tokens,
                            body_blocks=tuple(current_scope),
                            source_line=scope.source_line,
                        )
                    else:
                        scope = SemanticBlock(
                            BlockType.BLOCK,
                            body_blocks=tuple(current_scope),
                            source_line=scope.source_line,
                        )

                    # Replace the scope placeholder in parent's children
                    parent = scope_stack[-1]
                    # Find and replace — the scope placeholder is in parent's children
                    # Actually, we need to track children differently.
                    # Let me refactor...

            elif bt == BlockType.IF:
                _finish_pending()
                pending_if = block  # Condition captured, body follows

            elif bt == BlockType.WHILE:
                _finish_pending()
                pending_while = block

            elif bt == BlockType.ELSE:
                # Close current scope body, prepare for ELSE body
                if pending_if is not None:
                    # Single-statement IF body: pending_if still active
                    pass
                current_scope = []  # Start ELSE body fresh

            else:
                # Leaf block (SQL, ASSIGN, etc.)
                current_scope.append(block)

        if len(scope_stack) > 1:
            raise SegmentationError(
                f"Unclosed BEGIN at depth {len(scope_stack) - 1}",
                scope_stack[-1].source_line,
            )

        # Return root's body
        return list(root.body_blocks) if current_scope else []


# The tree builder is still too complex with this approach.
# Let me simplify completely — use a flat representation with depth info,
# which is sufficient for the IR extractor.

def _pass2_simple(self: _Segmenter, flat: list[SemanticBlock]) -> list[SemanticBlock]:
    """Simplified tree builder: absorb BEGIN/END into parent IF/WHILE blocks.

    Outer-most BEGIN/END pairs (at depth 0) are transparent — they don't
    create a BLOCK node. Only BEGIN/END inside IF/WHILE create scopes.

    Strategy:
    1. Walk flat blocks
    2. Track scope stack: only push for BEGIN inside IF/WHILE/ELSE
    3. BEGIN at root level is ignored (pass-through)
    4. END at root level signals end of procedure body
    """
    idx = 0
    n = len(flat)
    scope_stack: list[dict] = []  # Only inner scopes
    result: list[SemanticBlock] = []

    def _add_to_parent(child: SemanticBlock) -> None:
        """Add a child block to the current scope or result."""
        if scope_stack:
            scope_stack[-1]["children"].append(child)
        else:
            result.append(child)

    while idx < n:
        block = flat[idx]

        if block.block_type == BlockType.BLOCK:
            first_val = block.tokens[0].value.upper() if block.tokens else ""
            if first_val == "BEGIN":
                if scope_stack:
                    # Inner BEGIN — push a scope
                    scope_stack.append({
                        "kind": "block",
                        "header_tokens": (),
                        "children": [],
                        "line": block.source_line,
                    })
                # else: root-level BEGIN, ignore (pass-through)
            else:
                # END
                if scope_stack:
                    scope = scope_stack.pop()
                    kind = scope["kind"]
                    header = tuple(scope["header_tokens"])
                    children = tuple(scope["children"])

                    if kind == "if":
                        compound = SemanticBlock(
                            BlockType.IF,
                            header_tokens=header,
                            body_blocks=children,
                            source_line=scope["line"],
                        )
                    elif kind == "while":
                        compound = SemanticBlock(
                            BlockType.WHILE,
                            header_tokens=header,
                            body_blocks=children,
                            source_line=scope["line"],
                        )
                    else:
                        compound = SemanticBlock(
                            BlockType.BLOCK,
                            body_blocks=children,
                            source_line=scope["line"],
                        )
                    _add_to_parent(compound)
                # else: root-level END (outer block close), ignore

        elif block.block_type == BlockType.IF:
            # Check if body starts with BEGIN
            has_begin = (
                idx + 1 < n
                and flat[idx + 1].block_type == BlockType.BLOCK
                and flat[idx + 1].tokens
                and flat[idx + 1].tokens[0].value.upper() == "BEGIN"
            )
            if has_begin:
                scope_stack.append({
                    "kind": "if",
                    "header_tokens": block.header_tokens,
                    "children": [],
                    "line": block.source_line,
                })
                idx += 1  # skip past IF, BEGIN will be consumed next
            elif idx + 1 < n:
                # Single-statement body
                body_block = flat[idx + 1]
                compound = SemanticBlock(
                    BlockType.IF,
                    header_tokens=block.header_tokens,
                    body_blocks=(body_block,),
                    source_line=block.source_line,
                )
                _add_to_parent(compound)
                idx += 1  # skip body

        elif block.block_type == BlockType.WHILE:
            has_begin = (
                idx + 1 < n
                and flat[idx + 1].block_type == BlockType.BLOCK
                and flat[idx + 1].tokens
                and flat[idx + 1].tokens[0].value.upper() == "BEGIN"
            )
            if has_begin:
                scope_stack.append({
                    "kind": "while",
                    "header_tokens": block.header_tokens,
                    "children": [],
                    "line": block.source_line,
                })
                idx += 1
            elif idx + 1 < n:
                body_block = flat[idx + 1]
                compound = SemanticBlock(
                    BlockType.WHILE,
                    header_tokens=block.header_tokens,
                    body_blocks=(body_block,),
                    source_line=block.source_line,
                )
                _add_to_parent(compound)
                idx += 1

        elif block.block_type == BlockType.ELSE:
            # For IF...ELSE: the ELSE closes the current scope (which is the IF's THEN body)
            # and starts a new scope for the ELSE body
            if scope_stack and scope_stack[-1]["kind"] == "if":
                # Close the IF's THEN body scope
                if_scope = scope_stack.pop()
                # We'll handle the full IF/ELSE merge when END closes the ELSE body
                # For now, push ELSE as a new scope under a modified IF marker
                scope_stack.append({
                    "kind": "if",
                    "header_tokens": if_scope["header_tokens"],
                    "children": if_scope["children"],  # THEN body
                    "line": if_scope["line"],
                })
                # Mark as having ELSE
                scope_stack[-1]["has_else"] = True

            # Push ELSE body scope
            has_begin = (
                idx + 1 < n
                and flat[idx + 1].block_type == BlockType.BLOCK
                and flat[idx + 1].tokens
                and flat[idx + 1].tokens[0].value.upper() == "BEGIN"
            )
            if has_begin:
                scope_stack.append({
                    "kind": "else_body",
                    "header_tokens": (),
                    "children": [],
                    "line": block.source_line,
                })
                idx += 1
            elif idx + 1 < n:
                # Single-statement ELSE body
                scope_stack.append({
                    "kind": "else_body",
                    "header_tokens": (),
                    "children": [flat[idx + 1]],
                    "line": block.source_line,
                })
                idx += 1

        else:
            # Leaf block: DECLARE, ASSIGN, SQL, EXEC, RETURN, PRINT, UNKNOWN
            _add_to_parent(block)

        idx += 1

    # At end, any remaining scopes are unclosed (error) or root-level
    # Pop any remaining inner scopes into result
    while scope_stack:
        scope = scope_stack.pop()
        kind = scope["kind"]
        header = tuple(scope["header_tokens"])
        children = tuple(scope["children"])

        if kind == "if":
            # Check for ELSE body
            has_else = scope.get("has_else", False)
            else_body: tuple[SemanticBlock, ...] = ()
            # If the next scope (if any) is the else_body, merge it
            compound = SemanticBlock(
                BlockType.IF,
                header_tokens=header,
                body_blocks=children,
                has_else=has_else,
                source_line=scope["line"],
            )
        elif kind == "while":
            compound = SemanticBlock(
                BlockType.WHILE,
                header_tokens=header,
                body_blocks=children,
                source_line=scope["line"],
            )
        elif kind == "else_body":
            # ELSE body needs to be attached to the preceding IF
            # This should be handled above
            compound = SemanticBlock(
                BlockType.ELSE,
                body_blocks=children,
                source_line=scope["line"],
            )
        else:
            compound = SemanticBlock(
                BlockType.BLOCK,
                body_blocks=children,
                source_line=scope["line"],
            )
        _add_to_parent(compound)

    return result


# Override _pass2 with the simple version
_Segmenter._pass2 = _pass2_simple
