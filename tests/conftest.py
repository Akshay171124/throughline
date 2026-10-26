import pytest

from throughline import api
from throughline.graph import connect


@pytest.fixture(autouse=True)
def local_registry(monkeypatch):
    """API tests that don't set up a registry get a throwaway local one, and any graph the API opens
    is local: tests never reach the hosted lab, even when FALKORDB_URL is set."""
    monkeypatch.setattr(api, "connect", lambda name=None, local=False: connect(name, local=True))
    made = []

    def registry():
        if not made:
            made.append(connect("throughline_test_registry_default", local=True))
        return made[0]

    monkeypatch.setattr(api, "registry", registry)
    yield
    for g in made:
        try:
            g.delete()
        except Exception:  # never written to
            pass
