"""
Code Generator Protocol and Factory — matches the adapter factory pattern.

All generators implement the CodeGenerator Protocol, which takes an IRProcedure
and returns a string of executable target-dialect code.

The factory uses a registry pattern (matching sandbox/adapter/factory.py)
so that new targets can be added by registering a new class.

Usage:
    from sql_compiler.generator import create_generator

    generator = create_generator("kingbasees")
    code = generator.generate(ir)
"""

from __future__ import annotations

from typing import Protocol, Type

from ..ir import IRProcedure


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


class CodeGenerator(Protocol):
    """Protocol for IR → target code generators.

    Each implementation (PL/pgSQL, DM) produces executable procedure code
    in the target dialect from the same IR. The IR is the single source of
    truth — generators are purely "renderers."

    Usage:
        >>> generator = create_generator("kingbasees")
        >>> code: str = generator.generate(ir_procedure)
    """

    def generate(self, ir: IRProcedure) -> str:
        """Generate target-dialect procedure code from IR.

        Args:
            ir: The validated IRProcedure to generate code for.

        Returns:
            Complete, executable procedure source code in the target dialect.
        """
        ...


# ---------------------------------------------------------------------------
# Registry-based factory
# ---------------------------------------------------------------------------


_GENERATOR_REGISTRY: dict[str, Type[CodeGenerator]] = {}


def register_generator(db_type: str, generator_cls: Type[CodeGenerator]) -> None:
    """Register a code generator class for a database type.

    Args:
        db_type: Database type identifier ("kingbasees", "dm8").
        generator_cls: Class implementing CodeGenerator Protocol.
    """
    _GENERATOR_REGISTRY[db_type] = generator_cls


def create_generator(target_db: str) -> CodeGenerator:
    """Create a code generator for the target database.

    Args:
        target_db: Target database type ("kingbasees" or "dm8").

    Returns:
        A CodeGenerator instance.

    Raises:
        ValueError: If no generator is registered for the given target_db.
    """
    cls = _GENERATOR_REGISTRY.get(target_db)
    if cls is None:
        available = sorted(_GENERATOR_REGISTRY.keys())
        raise ValueError(
            f"No generator registered for '{target_db}'. "
            f"Available: {available}"
        )
    return cls()


def list_generators() -> list[str]:
    """List all registered code generator types."""
    return sorted(_GENERATOR_REGISTRY.keys())
