"""
Migration Sandbox Test Harness — deterministic migration validation framework.

Architecture:
    Test Case Layer → Sandbox Data Layer → Test Runner
    → API/ORM/SQL Execution → Dual DB Execution → Diff Engine
    → Report System

核心能力:
    1. Fixed dataset (deterministic, identical across MSSQL/KingbaseES/DM8)
    2. Structured test cases (API, SQL, ORM, schema scenarios)
    3. Repeatable execution pipeline (reset → run → diff → report)
    4. Integration with existing SQLKernel + explanation_engine

Usage:
    from app.sandbox.runner import MigrationTestRunner
    from app.sandbox.test_case import get_all_test_cases
    from app.sandbox.reporter import TestReport

Lazy imports — import submodules directly to avoid circular deps:
    from app.sandbox.data import SANDBOX_DATASET
    from app.sandbox.seeder import SandboxSeeder
    from app.sandbox.runner import MigrationTestRunner
"""
