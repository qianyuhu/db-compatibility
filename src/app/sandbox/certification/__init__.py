"""
Migration Certification Engine — confidence-driven certification model.

Replaces the old Risk-driven model with a proper separation of concerns:
  - Coverage = uncertainty (NOT risk)
  - Risk = actual failures only
  - Confidence = PassRate × 0.4 + CoverageQuality × 0.4 + Consistency × 0.2
  - Decision = confidence + failure_rate → READY / NOT_READY / REVIEW_REQUIRED

Architecture:
    Test Results → CoverageAnalyzer → CertificationEngine
                 → RiskScorer        →       |
                 → ConfidenceScorer  →       v
                 → DecisionEngine    → CertificationReport

Usage:
    from app.sandbox.certification.engine import CertificationEngine
    from app.sandbox.certification.schemas import CertificationReport
"""
