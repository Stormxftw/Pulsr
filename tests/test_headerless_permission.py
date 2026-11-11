"""Original headerless permission reproduction for issue #72; real Net, offline."""
import pytest
from pulse_rings.net import Net, _http_error
from pulse_rings.store import Store
from pulse_rings.sources.base import SourceError

@pytest.mark.parametrize("message", ["Resource not accessible by integration", "Resource not accessible by personal access token"])
def test_recognized_headerless_permission_error_does_not_gate_other_feeds(tmp_path,monkeypatch,message):
 import json
 now=1794000000
 store=Store(tmp_path);net=Net(store,clock=lambda:now)
 def deny(*a,**kw):raise _http_error(403,{},json.dumps({"message":message}).encode(),now=now)
 monkeypatch.setattr("pulse_rings.net.fetch_bytes",deny)
 with pytest.raises(SourceError):net.bytes("https://api.github.com/repos/offline/repo/actions/runs?per_page=1")
 assert store.gate("remote:api.github.com")==0, "Original headerless permission case still rate-gates unrelated feeds"
 assert store.gate("host:api.github.com")==now+2, "Ordinary pacing must remain"
