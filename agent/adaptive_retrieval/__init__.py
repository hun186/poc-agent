"""Separate adaptive query *planning* from initial keyword extraction.

This package is not connected to the production Agent, ES or ReportJobWorker.
The existing first-round search and canonical Evidence validation remain the
only execution authority. See docs/operations/sraf_adaptive_planner_boundary.md.
"""
from .contracts import BudgetSnapshot, DateWindow, QueryConstraints, RoundEvidenceSummary
from .planner import AdaptiveRetrievalPlanner, PlannerDecision

__all__ = [
    "AdaptiveRetrievalPlanner", "BudgetSnapshot", "DateWindow",
    "PlannerDecision", "QueryConstraints", "RoundEvidenceSummary",
]
