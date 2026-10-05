"""Shared fixtures."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from .fake_routeros import FakeApi, sample_router


@pytest.fixture
def fake_api() -> FakeApi:
    return FakeApi(sample_router())


@pytest.fixture
def mock_connect(fake_api: FakeApi):
    with patch(
        "custom_components.mikrotik_api.router.librouteros.connect",
        return_value=fake_api,
    ) as connect:
        yield connect


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(request):
    """Only HA tests need the hass fixture; enable custom integrations there."""
    if "hass" in request.fixturenames:
        request.getfixturevalue("enable_custom_integrations")
    yield
