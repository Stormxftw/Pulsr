"""Inverted N4 probes and live, unsampled Hermes waiting state."""
import random
from pathlib import Path
from types import SimpleNamespace

from pulse_rings.engine import Engine
from pulse_rings.hooks import register_hooks
from pulse_rings.spec import normalize

NOW = 1_794_000_000.0
DEFINITION = normalize((Path(__file__).resolve().parents[1] / 'examples/c-hermes.pulse.yaml').read_text())


def test_hermes_max_jitter_never_stale_between_samples(tmp_path, monkeypatch):
    monkeypatch.setattr(random, 'uniform', lambda a, b: b)
    clock = [NOW]
    engine = Engine(tmp_path, clock=lambda: clock[0])
    engine.activate(DEFINITION)
    assert engine.poll_one_due()
    assert engine.store.rows()[0]['next_due'] <= NOW + 36
    for offset in (15, 30, 45, 60, 75, 90):
        clock[0] = NOW + offset
        engine.poll_one_due()
        assert engine.status()['pulses'][0]['state'] != 'stale'


def test_waiting_current_and_events_without_another_sample(tmp_path, monkeypatch):
    engine = Engine(tmp_path, clock=lambda: NOW, jitter=lambda: 0)
    hooks, emitted = {}, []
    monkeypatch.setattr('pulse_rings.events.emit', lambda *args: emitted.append(args))
    rec = register_hooks(SimpleNamespace(register_hook=lambda n, cb: hooks.update({n: cb})),
                         store=engine.store, clock=lambda: NOW)
    try:
        engine.activate(DEFINITION)
        engine.poll_one_due()
        history = engine.store.history(DEFINITION['id'])
        hooks['on_human_input_request'](kind='clarify', request_id='r')
        row = engine.status()['pulses'][0]
        assert row['alert']['active']
        current = engine.adapter(DEFINITION).current(history[-1], {}, now=NOW)
        assert current['metrics']['waiting_on_you'] == 1
        assert history[-1]['metrics']['waiting_on_you'] == 0
        hooks['on_human_input_resolved'](kind='clarify', request_id='r')
        assert not engine.status()['pulses'][0]['alert']['active']
        assert engine.adapter(DEFINITION).current(history[-1], {}, now=NOW)['metrics']['waiting_on_you'] == 0
        assert engine.store.history(DEFINITION['id']) == history
        assert emitted == [('hermes.waiting', {}), ('hermes.waiting', {})]
    finally:
        rec.close()


def test_queued_waiting_close_emits_after_flush_outside_recorder_lock(tmp_path, monkeypatch):
    engine = Engine(tmp_path, clock=lambda: NOW)
    hooks, emitted = {}, []
    rec = register_hooks(SimpleNamespace(register_hook=lambda n, cb: hooks.update({n: cb})), store=engine.store, clock=lambda: NOW)
    assert rec is not None
    def emit(name, payload):
        assert not rec.lock.locked()
        emitted.append(name)
    monkeypatch.setattr('pulse_rings.events.emit', emit)
    try:
        hooks['on_human_input_request'](kind='clarify', request_id='r')
        rec.lock.acquire()
        try:
            hooks['on_human_input_resolved'](kind='clarify', request_id='r')
        finally:
            rec.lock.release()
        rec.flush_pending()
        assert emitted == ['hermes.waiting', 'hermes.waiting']
    finally:
        rec.close()
