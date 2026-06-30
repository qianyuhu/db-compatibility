"""
Migration Execution & Continuous Fix Engine (Phase 3).

Architecture:
    Sandbox Tests → Execution Engine → Diff Engine → Issue Classifier
    → Fix Strategy Engine → Re-Execution Loop → Issue Tracker → Report + UI

Core Principle: ALWAYS execute, NEVER block. Detect → Classify → Fix → Re-run → Verify.

Usage:
    from app.sandbox.execution.loop_engine import MigrationExecutionLoop

    loop = MigrationExecutionLoop(source_db="mssql", target_db="kingbasees")
    state = loop.run_full_loop()  # Run until stabilization or max iterations
    report = loop.get_execution_report()

Module Structure:
    schemas.py    — Data structures (MigrationIssue, FixStrategy, ExecutionReport, etc.)
    classifier.py — IssueClassifier: failure → typed issue with root cause
    fix_engine.py — FixStrategyEngine: issue → fix plan → fix application
    tracker.py    — IssueTracker: lifecycle state machine
    loop_engine.py— MigrationExecutionLoop: main orchestrator
"""
