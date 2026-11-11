"""All tests are profile-isolated; migration offers never probe live user data."""
import sys
from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def isolated_hermes_home(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, 'hermes_constants',
                        SimpleNamespace(get_hermes_home=lambda: tmp_path / 'hermes-home'))
