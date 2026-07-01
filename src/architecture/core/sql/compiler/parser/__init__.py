"""
Parser package — T-SQL Lexer, Block Segmenter, Control Flow Extractor.

Pipeline:
    T-SQL text → tokenize() → tokens
    tokens → segment_blocks() → SemanticBlocks
    blocks → extract_ir_nodes() → IR nodes
"""

from .lexer import Token, TokenType, LexerError, tokenize, split_batches
from .block_segmenter import (
    SemanticBlock,
    BlockType,
    SegmentationError,
    segment_blocks,
)
from .control_flow_extractor import (
    ExtractionError,
    extract_ir_nodes,
)

__all__ = [
    # Lexer
    "Token",
    "TokenType",
    "LexerError",
    "tokenize",
    "split_batches",
    # Block Segmenter
    "SemanticBlock",
    "BlockType",
    "SegmentationError",
    "segment_blocks",
    # Control Flow Extractor
    "ExtractionError",
    "extract_ir_nodes",
]
