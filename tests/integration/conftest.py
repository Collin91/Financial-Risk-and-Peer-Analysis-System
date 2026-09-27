"""Shared fixture: one real Tesla / Ford / Toyota analysis for all integration tests.

Uses the local download cache; skipped when neither the cache nor the network is available.
"""

import pytest

from financial_analyzer.analysis import industries, pipeline


@pytest.fixture(scope="session")
def result():
    try:
        return pipeline.run("Tesla", ["Ford", "Toyota"], industries.get_profile("automotive"), 2021, 2025,
                            progress=lambda *a: None)
    except Exception as exc:  # no cache and no network
        pytest.skip(f"SEC data unavailable: {exc}")
