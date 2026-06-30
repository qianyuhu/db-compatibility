"""
Migration Risk Intelligence Layer — converts test results into risk intelligence.

Sits on top of Sandbox Test Harness to provide:
    - Multi-dimensional risk scoring (SQL, Schema, Data, API, Behavioral)
    - Migration readiness assessment (SAFE → BLOCKER)
    - Coverage analysis (SQL, API, ORM pattern coverage)
    - System-level migration confidence scoring

Architecture:
    Sandbox Test Harness → Diff Engine → MigrationRiskEngine
    → Coverage Analyzer → Confidence Scoring → Risk Report + UI

Usage:
    from app.sandbox.risk.engine import MigrationRiskEngine
    from app.sandbox.risk.scorer import RiskScorer
    from app.sandbox.risk.coverage import CoverageAnalyzer
    from app.sandbox.risk.confidence import ConfidenceScorer
"""
