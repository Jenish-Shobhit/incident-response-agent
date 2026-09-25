"""Shared test setup. Every test runs in mock mode, whatever a local .env says."""

import json
import os

os.environ["MOCK"] = "1"  # before any incident_agent import reads config

import pytest  # noqa: E402

from incident_agent import config  # noqa: E402
from incident_agent.evidence import normalise  # noqa: E402


@pytest.fixture(scope="session")
def raw_incident():
    """The bundled scenario's incident file, exactly as written."""
    with open(config.INCIDENT_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def incident(raw_incident):
    """The same incident, normalised into the shape the graph reads."""
    return normalise(raw_incident)


@pytest.fixture(scope="session")
def records(incident):
    return incident["evidence"]
