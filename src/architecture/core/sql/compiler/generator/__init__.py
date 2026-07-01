"""
Code Generators — IR → target dialect procedure code.

Registry-based factory (matching sandbox/adapter/factory.py pattern).
"""

from .base import (
    CodeGenerator,
    create_generator,
    list_generators,
    register_generator,
)
from .plpgsql import PlPgSQLGenerator
from .dm import DMGenerator

# Register at module load
register_generator("kingbasees", PlPgSQLGenerator)
register_generator("dm8", DMGenerator)

__all__ = [
    "CodeGenerator",
    "create_generator",
    "list_generators",
    "register_generator",
    "PlPgSQLGenerator",
    "DMGenerator",
]
