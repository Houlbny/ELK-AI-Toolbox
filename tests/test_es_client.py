from types import SimpleNamespace

from mcp_server.config import ElkConfig
from mcp_server.es_client import ElkClient


def make_config(mode: str, verify_certs: bool = True) -> ElkConfig:
    return ElkConfig(
        mode=mode,
        host="https://elk.example.com",
        username="elastic",
        password="secret",
        timeout_seconds=30,
        max_results=50,
        max_time_range_days=7,
        max_buckets=20,
        verify_certs=verify_certs,
        kibana_space="",
        timezone_offset_hours=8,
    )


def test_init_elasticsearch_mode_uses_verify_certs(monkeypatch):
    captured = {}

    class FakeElasticsearch:
        def __init__(self, *args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs

        def close(self):
            return None

    monkeypatch.setitem(__import__("sys").modules, "elasticsearch", SimpleNamespace(Elasticsearch=FakeElasticsearch))

    client = ElkClient(make_config(mode="elasticsearch", verify_certs=True))

    assert client._mode == "elasticsearch"
    assert captured["kwargs"]["verify_certs"] is True
    assert captured["kwargs"]["request_timeout"] == 30


def test_init_kibana_mode_uses_verify_certs(monkeypatch):
    captured = {}

    class FakeHttpClient:
        def __init__(self, *args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs

        def close(self):
            return None

    monkeypatch.setitem(__import__("sys").modules, "httpx", SimpleNamespace(Client=FakeHttpClient))

    client = ElkClient(make_config(mode="kibana", verify_certs=True))

    assert client._mode == "kibana"
    assert captured["kwargs"]["verify"] is True
    assert captured["kwargs"]["timeout"] == 30


def test_kibana_request_builds_proxy_request(monkeypatch):
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": True}

    class FakeHttpClient:
        def __init__(self, *args, **kwargs):
            pass

        def post(self, path, params=None, json=None):
            captured["path"] = path
            captured["params"] = params
            captured["json"] = json
            return FakeResponse()

        def close(self):
            return None

    monkeypatch.setitem(
        __import__("sys").modules,
        "httpx",
        SimpleNamespace(Client=FakeHttpClient, ConnectError=Exception, TimeoutException=Exception),
    )

    client = ElkClient(make_config(mode="kibana"))
    result = client._kibana_request("GET", "/_cat/indices?format=json", {"size": 1})

    assert result == {"ok": True}
    assert captured["path"] == "/api/console/proxy"
    assert captured["params"] == {"path": "/_cat/indices?format=json", "method": "GET"}
    assert captured["json"] == {"size": 1}


def test_delegates_in_elasticsearch_mode(monkeypatch):
    class FakeCat:
        def indices(self, **kwargs):
            return [{"index": "logs"}]

    class FakeIndices:
        def get_mapping(self, **kwargs):
            return {"logs": {"mappings": {}}}

    class FakeElasticsearch:
        def __init__(self, *args, **kwargs):
            self.cat = FakeCat()
            self.indices = FakeIndices()

        def count(self, **kwargs):
            return {"count": 7}

        def search(self, **kwargs):
            return {"hits": {"hits": []}}

        def close(self):
            return None

    monkeypatch.setitem(__import__("sys").modules, "elasticsearch", SimpleNamespace(Elasticsearch=FakeElasticsearch))

    client = ElkClient(make_config(mode="elasticsearch"))

    assert client.cat_indices("logs-*") == [{"index": "logs"}]
    assert client.get_mapping("logs") == {"logs": {"mappings": {}}}
    assert client.count("logs") == 7
    assert client.search("logs", {"query": {"match_all": {}}}) == {"hits": {"hits": []}}


def test_delegates_in_kibana_mode(monkeypatch):
    class FakeHttpClient:
        def __init__(self, *args, **kwargs):
            pass

        def close(self):
            return None

    monkeypatch.setitem(__import__("sys").modules, "httpx", SimpleNamespace(Client=FakeHttpClient))

    client = ElkClient(make_config(mode="kibana"))

    calls = []

    def fake_request(method, path, body=None):
        calls.append((method, path, body))
        if path.endswith("/_count"):
            return {"count": 3}
        return {"ok": True}

    client._kibana_request = fake_request

    assert client.count("logs", {"query": {"match_all": {}}}) == 3
    assert client.search("logs", {"query": {"match_all": {}}}) == {"ok": True}
    assert client.cat_indices("logs-*") == {"ok": True}
    assert client.get_mapping("logs") == {"ok": True}

    assert calls[0] == ("POST", "/logs/_count", {"query": {"match_all": {}}})
    assert calls[1] == ("POST", "/logs/_search", {"query": {"match_all": {}}})
    assert calls[2] == ("GET", "/_cat/indices/logs-*?format=json&h=index,docs.count,store.size", None)
    assert calls[3] == ("GET", "/logs/_mapping", None)


def test_init_elasticsearch_mode_uses_verify_certs_false(monkeypatch):
    captured = {}

    class FakeElasticsearch:
        def __init__(self, *args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs

        def close(self):
            return None

    monkeypatch.setitem(__import__("sys").modules, "elasticsearch", SimpleNamespace(Elasticsearch=FakeElasticsearch))

    client = ElkClient(make_config(mode="elasticsearch", verify_certs=False))

    assert client._mode == "elasticsearch"
    assert captured["kwargs"]["verify_certs"] is False


def test_init_kibana_mode_uses_verify_certs_false(monkeypatch):
    captured = {}

    class FakeHttpClient:
        def __init__(self, *args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs

        def close(self):
            return None

    monkeypatch.setitem(__import__("sys").modules, "httpx", SimpleNamespace(Client=FakeHttpClient))

    client = ElkClient(make_config(mode="kibana", verify_certs=False))

    assert client._mode == "kibana"
    assert captured["kwargs"]["verify"] is False


def test_invalid_mode_raises_value_error():
    from pytest import raises

    with raises(ValueError, match="Invalid mode: 'unknown'"):
        ElkClient(make_config(mode="unknown"))


def test_close_closes_active_backend(monkeypatch):
    class FakeElasticsearch:
        def __init__(self, *args, **kwargs):
            self.closed = False

        def close(self):
            self.closed = True

    class FakeHttpClient:
        def __init__(self, *args, **kwargs):
            self.closed = False

        def close(self):
            self.closed = True

    monkeypatch.setitem(__import__("sys").modules, "elasticsearch", SimpleNamespace(Elasticsearch=FakeElasticsearch))
    monkeypatch.setitem(__import__("sys").modules, "httpx", SimpleNamespace(Client=FakeHttpClient))

    es_client = ElkClient(make_config(mode="elasticsearch"))
    kb_client = ElkClient(make_config(mode="kibana"))

    es_client.close()
    kb_client.close()

    assert es_client._es.closed is True
    assert kb_client._http.closed is True


def test_context_manager(monkeypatch):
    class FakeElasticsearch:
        def __init__(self, *args, **kwargs):
            self.closed = False

        def close(self):
            self.closed = True

    monkeypatch.setitem(__import__("sys").modules, "elasticsearch", SimpleNamespace(Elasticsearch=FakeElasticsearch))

    with ElkClient(make_config(mode="elasticsearch")) as client:
        assert client._mode == "elasticsearch"

    assert client._es.closed is True
