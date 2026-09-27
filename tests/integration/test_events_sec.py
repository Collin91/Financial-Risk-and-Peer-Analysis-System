"""SEC Event Context module against real data: isolation from calculations and change detection."""

import copy

import pytest

from financial_analyzer import events

pytestmark = pytest.mark.integration


def test_retrieval_failure_is_recorded_not_raised_and_scores_unchanged(result, monkeypatch):
    r = copy.deepcopy(result)
    before_scores = r.scores.copy()
    before_metrics = r.metrics_all.copy()

    def boom(*args, **kwargs):
        raise RuntimeError("EDGAR unreachable")

    monkeypatch.setattr(events, "events_for_period", boom)
    events.attach(r, progress=lambda *a: None)
    assert r.events_run and r.events == []
    assert r.event_errors and "EDGAR unreachable" in r.event_errors[0]
    assert r.scores.equals(before_scores)
    assert r.metrics_all.equals(before_metrics)


def test_significant_changes_detected_for_latest_period(result):
    changes = events.detect_changes(result, [2025])
    ford = {c.area for c in changes if c.company == "Ford"}
    assert events.PROFITABILITY in ford
    toyota = [c for c in changes if c.company == "Toyota"]
    assert toyota and all(c.reported_fiscal_year == "FY2026" for c in toyota)
