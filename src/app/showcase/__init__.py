"""
Migration Capability Showcase — interactive multi-DB demo scenes.

This module powers the "场景展示 (Scene Showcase)" tab in the frontend.
It provides pre-defined demo scenes (NOT test cases) that visually
demonstrate multi-database compatibility across MSSQL, KingbaseES, and DM8.

Architecture:
    scenes.py  → Scene definitions (SQL/API/ORM, metadata, insights)
    engine.py  → Scene execution engine (parallel DB execution + diff)

Key design principle:
    This is a SHOWCASE (可视化演示), NOT a test system.
    Each scene demonstrates one migration capability with visual
    side-by-side results, not pass/fail assertions.
"""
