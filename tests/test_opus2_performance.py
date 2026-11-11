"""Status read scope, immutable icon delivery and schema-cache regressions."""
import json
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from pulse_rings.engine import Engine
from pulse_rings.spec import normalize
from pulse_rings.store import Store

ROOT = Path(__file__).resolve().parents[1]
NOW = 1_794_000_000.0


def test_status_reuses_one_connection_and_has_no_legacy_aliases(tmp_path, monkeypatch):
    engine = Engine(tmp_path, clock=lambda: NOW)
    base = normalize((ROOT / 'examples/a-discord.pulse.yaml').read_text())
    for i in range(24):
        engine.activate(dict(base, id=f'pulse-{i}'), sample={'ts': NOW, 'metrics': {'online': i, 'members': 100}})
    original = engine.store.db
    opened = []
    def connect(*a, **kw):
        opened.append(1)
        return original(*a, **kw)
    monkeypatch.setattr(engine.store, 'db', connect)
    status = engine.status()
    assert len(opened) == 1
    assert not {'servers', 'curated'} & status.keys()
    assert len(json.dumps(status).encode()) < 120 * 1024


def test_store_schema_ddl_once_per_process_root(tmp_path):
    store = Store(tmp_path)
    original = Store.db
    statements = []
    def connect(self, *a, **kw):
        db = original(self, *a, **kw)
        db.set_trace_callback(statements.append)
        return db
    with patch.object(Store, 'db', connect):
        Store(tmp_path)
        Store(tmp_path)
    assert not any(s.lstrip().upper().startswith(('CREATE ', 'ALTER ')) for s in statements)
    with closing(store.db()) as db, db:
        db.execute("UPDATE meta SET value='2' WHERE key='schema_version'")
    import pytest
    with pytest.raises(ValueError, match='schema'):
        Store(tmp_path)
