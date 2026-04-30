import json

import pytest
from mcp_server.config import ElkConfig
from mcp_server.tools import aggregate, count, field_values, indices, mapping, search, server_time
from mcp_server.tools.errors import build_queried_time_range
from mcp_server.tools.parse import parse_json_like


class FakeMCP:
    def __init__(self):
        self.tools = {}

    def tool(self):
        def decorator(func):
            self.tools[func.__name__] = func
            return func

        return decorator


class FakeClient:
    def __init__(self):
        self.last_count = None
        self.last_search = None
        self.last_mapping = None
        self.last_indices = None
        self.indices_calls = []

    def count(self, index, body=None):
        self.last_count = (index, body)
        return 3

    def search(self, index, body):
        self.last_search = (index, body)
        return {"hits": {"total": {"value": 0}, "hits": []}, "aggregations": {}}

    def get_mapping(self, index):
        self.last_mapping = index
        return {
            index: {
                "mappings": {
                    "properties": {
                        "message": {"type": "text"},
                    }
                }
            }
        }

    def cat_indices(self, pattern):
        self.last_indices = pattern
        self.indices_calls.append(pattern)
        return []


def make_config(max_results=50, max_buckets=20, timezone_offset_hours=8):
    return ElkConfig(
        mode="elasticsearch",
        host="https://elk.example.com",
        username="elastic",
        password="secret",
        timeout_seconds=30,
        max_results=max_results,
        max_time_range_days=7,
        max_buckets=max_buckets,
        verify_certs=True,
        timezone_offset_hours=timezone_offset_hours,
    )


# --- parse_json_like ---

def test_parse_json_like_accepts_dict_and_string_json():
    assert parse_json_like({"match_all": {}}, "query") == {"match_all": {}}
    assert parse_json_like('{"match_all": {}}', "query") == {"match_all": {}}


def test_parse_json_like_rejects_totally_invalid():
    with pytest.raises(ValueError) as exc:
        parse_json_like("not json at all", "query")
    assert "query" in str(exc.value)


def test_parse_json_like_fixes_missing_closing_brace():
    result = parse_json_like('{"term": {"level": "ERROR"}', "query")
    assert result == {"term": {"level": "ERROR"}}


def test_parse_json_like_fixes_double_escaped_quotes():
    result = parse_json_like('{\\"term\\": {\\"level\\": \\"ERROR\\"}}', "query")
    assert result == {"term": {"level": "ERROR"}}


def test_parse_json_like_fixes_single_quotes():
    result = parse_json_like("{'term': {'level': 'ERROR'}}", "query")
    assert result == {"term": {"level": "ERROR"}}


def test_parse_json_like_fixes_trailing_comma():
    result = parse_json_like('{"term": {"level": "ERROR"},}', "query")
    assert result == {"term": {"level": "ERROR"}}


def test_parse_json_like_accepts_list():
    result = parse_json_like([{"@timestamp": "desc"}], "sort")
    assert result == [{"@timestamp": "desc"}]


# --- es_count ---

def test_es_count_returns_json_parse_error_for_invalid_query():
    mcp = FakeMCP()
    client = FakeClient()
    count.register(mcp, client, make_config())

    result = json.loads(mcp.tools["es_count"]("logs-*", query="not json"))

    assert result["error"]["type"] == "invalid_json"
    assert result["error"]["field"] == "query"


def test_es_count_blocks_internal_index():
    mcp = FakeMCP()
    client = FakeClient()
    count.register(mcp, client, make_config())

    result = json.loads(mcp.tools["es_count"](".kibana"))

    assert result["error"]["type"] == "guard_error"
    assert "internal index" in result["error"]["message"]


def test_es_count_with_time_range():
    mcp = FakeMCP()
    client = FakeClient()
    count.register(mcp, client, make_config())

    result = json.loads(mcp.tools["es_count"](
        "logs-*",
        time_field="@timestamp",
        start_time="2026-04-24T00:00:00",
        end_time="2026-04-24T01:00:00",
    ))

    assert result["count"] == 3
    body = client.last_count[1]
    assert "query" in body
    assert "bool" in body["query"]


def test_es_count_es_error_returns_structured_error():
    class ErrorClient(FakeClient):
        def count(self, index, body=None):
            raise ConnectionError("ES is down")

    mcp = FakeMCP()
    client = ErrorClient()
    count.register(mcp, client, make_config())

    result = json.loads(mcp.tools["es_count"]("logs-*"))

    assert result["error"]["type"] == "es_error"
    assert "ES is down" in result["error"]["message"]


# --- es_search ---

def test_es_search_returns_json_parse_error_for_invalid_query():
    mcp = FakeMCP()
    client = FakeClient()
    search.register(mcp, client, make_config())

    result = json.loads(
        mcp.tools["es_search"](
            index="logs-*",
            query="not json",
            time_field="@timestamp",
            start_time="2026-04-24T00:00:00",
            end_time="2026-04-24T01:00:00",
        )
    )

    assert result["error"]["type"] == "invalid_json"
    assert result["error"]["field"] == "query"


def test_es_search_returns_json_parse_error_for_invalid_sort():
    mcp = FakeMCP()
    client = FakeClient()
    search.register(mcp, client, make_config())

    result = json.loads(
        mcp.tools["es_search"](
            index="logs-*",
            query='{"match_all": {}}',
            time_field="@timestamp",
            start_time="2026-04-24T00:00:00",
            end_time="2026-04-24T01:00:00",
            sort="[",
        )
    )

    assert result["error"]["type"] == "invalid_json"
    assert result["error"]["field"] == "sort"


def test_es_search_clamps_size_to_max_results():
    mcp = FakeMCP()
    client = FakeClient()
    search.register(mcp, client, make_config(max_results=10))

    mcp.tools["es_search"](
        index="logs-*",
        query='{"match_all": {}}',
        time_field="@timestamp",
        start_time="2026-04-24T00:00:00",
        end_time="2026-04-24T01:00:00",
        size=99,
    )

    assert client.last_search[1]["size"] == 10


def test_es_search_returns_guard_error_for_invalid_size():
    mcp = FakeMCP()
    client = FakeClient()
    search.register(mcp, client, make_config())

    result = json.loads(
        mcp.tools["es_search"](
            index="logs-*",
            query='{"match_all": {}}',
            time_field="@timestamp",
            start_time="2026-04-24T00:00:00",
            end_time="2026-04-24T01:00:00",
            size=-1,
        )
    )

    assert result["error"]["type"] == "guard_error"
    assert "non-negative" in result["error"]["message"]


def test_es_search_blocks_internal_index():
    mcp = FakeMCP()
    client = FakeClient()
    search.register(mcp, client, make_config())

    result = json.loads(
        mcp.tools["es_search"](
            index=".security-7",
            query='{"match_all": {}}',
            time_field="@timestamp",
            start_time="2026-04-24T00:00:00",
            end_time="2026-04-24T01:00:00",
        )
    )

    assert result["error"]["type"] == "guard_error"
    assert "internal index" in result["error"]["message"]


def test_es_search_es_error_returns_structured_error():
    class ErrorClient(FakeClient):
        def search(self, index, body):
            raise ConnectionError("connection refused")

    mcp = FakeMCP()
    client = ErrorClient()
    search.register(mcp, client, make_config())

    result = json.loads(
        mcp.tools["es_search"](
            index="logs-*",
            query='{"match_all": {}}',
            time_field="@timestamp",
            start_time="2026-04-24T00:00:00",
            end_time="2026-04-24T01:00:00",
        )
    )

    assert result["error"]["type"] == "es_error"
    assert "connection refused" in result["error"]["message"]


def test_es_search_does_not_pollute_source():
    class DocClient(FakeClient):
        def search(self, index, body):
            return {
                "hits": {
                    "total": {"value": 1},
                    "hits": [
                        {"_index": "logs", "_id": "1", "_source": {"_index": "original", "message": "hello"}}
                    ],
                }
            }

    mcp = FakeMCP()
    client = DocClient()
    search.register(mcp, client, make_config())

    result = json.loads(
        mcp.tools["es_search"](
            index="logs-*",
            query='{"match_all": {}}',
            time_field="@timestamp",
            start_time="2026-04-24T00:00:00",
            end_time="2026-04-24T01:00:00",
        )
    )

    doc = result["docs"][0]
    assert doc["_index"] == "logs"
    assert doc["message"] == "hello"


def test_es_search_uses_timeout_seconds_in_body():
    mcp = FakeMCP()
    client = FakeClient()
    search.register(mcp, client, make_config())

    mcp.tools["es_search"](
        index="logs-*",
        query='{"match_all": {}}',
        time_field="@timestamp",
        start_time="2026-04-24T00:00:00",
        end_time="2026-04-24T01:00:00",
    )

    assert client.last_search[1]["timeout"] == "30s"


def test_es_search_uses_relative_minutes_for_time_range(monkeypatch):
    def fake_resolve_time_range(start_time, end_time, relative_minutes, timezone_offset_hours):
        assert start_time is None
        assert end_time is None
        assert relative_minutes == 30
        assert timezone_offset_hours == 8
        return "2026-04-29T10:00:00+08:00", "2026-04-29T10:30:00+08:00"

    monkeypatch.setattr(search, "resolve_time_range", fake_resolve_time_range)
    mcp = FakeMCP()
    client = FakeClient()
    search.register(mcp, client, make_config())

    mcp.tools["es_search"](
        index="logs-*",
        query={"match_all": {}},
        time_field="@timestamp",
        relative_minutes=30,
    )

    time_filter = client.last_search[1]["query"]["bool"]["filter"][0]["range"]["@timestamp"]
    assert time_filter == {
        "gte": "2026-04-29T02:00:00.000Z",
        "lte": "2026-04-29T02:30:00.000Z",
    }


# --- es_aggregate ---

def test_es_aggregate_returns_json_parse_error_for_invalid_query_and_aggs():
    mcp = FakeMCP()
    client = FakeClient()
    aggregate.register(mcp, client, make_config())

    query_error = json.loads(
        mcp.tools["es_aggregate"](
            index="logs-*",
            aggs='{"levels": {"terms": {"field": "level"}}}',
            time_field="@timestamp",
            start_time="2026-04-24T00:00:00",
            end_time="2026-04-24T01:00:00",
            query="not json",
        )
    )
    aggs_error = json.loads(
        mcp.tools["es_aggregate"](
            index="logs-*",
            aggs="not json",
            time_field="@timestamp",
            start_time="2026-04-24T00:00:00",
            end_time="2026-04-24T01:00:00",
        )
    )

    assert query_error["error"]["type"] == "invalid_json"
    assert query_error["error"]["field"] == "query"
    assert aggs_error["error"]["type"] == "invalid_json"
    assert aggs_error["error"]["field"] == "aggs"


def test_es_aggregate_default_size_zero_and_clamp_size():
    mcp = FakeMCP()
    client = FakeClient()
    aggregate.register(mcp, client, make_config(max_results=7))

    mcp.tools["es_aggregate"](
        index="logs-*",
        aggs='{"levels": {"terms": {"field": "level"}}}',
        time_field="@timestamp",
        start_time="2026-04-24T00:00:00",
        end_time="2026-04-24T01:00:00",
    )
    default_size = client.last_search[1]["size"]

    mcp.tools["es_aggregate"](
        index="logs-*",
        aggs='{"levels": {"terms": {"field": "level"}}}',
        time_field="@timestamp",
        start_time="2026-04-24T00:00:00",
        end_time="2026-04-24T01:00:00",
        size=100,
    )
    clamped_size = client.last_search[1]["size"]

    assert default_size == 0
    assert clamped_size == 7


def test_es_aggregate_uses_relative_minutes_for_time_range(monkeypatch):
    def fake_resolve_time_range(start_time, end_time, relative_minutes, timezone_offset_hours):
        assert start_time is None
        assert end_time is None
        assert relative_minutes == 30
        assert timezone_offset_hours == 8
        return "2026-04-29T10:00:00+08:00", "2026-04-29T10:30:00+08:00"

    monkeypatch.setattr(aggregate, "resolve_time_range", fake_resolve_time_range)
    mcp = FakeMCP()
    client = FakeClient()
    aggregate.register(mcp, client, make_config())

    mcp.tools["es_aggregate"](
        index="logs-*",
        aggs={"avg_response_time": {"avg": {"field": "time_request"}}},
        time_field="@timestamp",
        relative_minutes=30,
    )

    body = client.last_search[1]
    time_filter = body["query"]["bool"]["filter"][0]["range"]["@timestamp"]
    assert time_filter == {
        "gte": "2026-04-29T02:00:00.000Z",
        "lte": "2026-04-29T02:30:00.000Z",
    }
    assert body["size"] == 0


def test_es_aggregate_truncates_buckets():
    class AggClient(FakeClient):
        def search(self, index, body):
            self.last_search = (index, body)
            return {
                "hits": {"total": {"value": 30}},
                "aggregations": {
                    "levels": {
                        "buckets": [{"key": str(i), "doc_count": i} for i in range(30)]
                    }
                },
            }

    mcp = FakeMCP()
    client = AggClient()
    aggregate.register(mcp, client, make_config())

    result = json.loads(
        mcp.tools["es_aggregate"](
            index="logs-*",
            aggs='{"levels": {"terms": {"field": "level"}}}',
            time_field="@timestamp",
            start_time="2026-04-24T00:00:00",
            end_time="2026-04-24T01:00:00",
        )
    )

    buckets = result["aggregations"]["levels"]["buckets"]
    assert len(buckets) == 20
    assert result["aggregations"]["levels"]["_truncated"] is True


def test_es_aggregate_custom_max_buckets():
    class AggClient(FakeClient):
        def search(self, index, body):
            self.last_search = (index, body)
            return {
                "hits": {"total": {"value": 30}},
                "aggregations": {
                    "levels": {
                        "buckets": [{"key": str(i), "doc_count": i} for i in range(30)]
                    }
                },
            }

    mcp = FakeMCP()
    client = AggClient()
    aggregate.register(mcp, client, make_config(max_buckets=10))

    result = json.loads(
        mcp.tools["es_aggregate"](
            index="logs-*",
            aggs='{"levels": {"terms": {"field": "level"}}}',
            time_field="@timestamp",
            start_time="2026-04-24T00:00:00",
            end_time="2026-04-24T01:00:00",
        )
    )

    buckets = result["aggregations"]["levels"]["buckets"]
    assert len(buckets) == 10
    assert result["aggregations"]["levels"]["_truncated"] is True


def test_es_aggregate_blocks_internal_index():
    mcp = FakeMCP()
    client = FakeClient()
    aggregate.register(mcp, client, make_config())

    result = json.loads(
        mcp.tools["es_aggregate"](
            index=".kibana_1",
            aggs='{"levels": {"terms": {"field": "level"}}}',
            time_field="@timestamp",
            start_time="2026-04-24T00:00:00",
            end_time="2026-04-24T01:00:00",
        )
    )

    assert result["error"]["type"] == "guard_error"
    assert "internal index" in result["error"]["message"]


def test_es_aggregate_es_error_returns_structured_error():
    class ErrorClient(FakeClient):
        def search(self, index, body):
            raise ConnectionError("timeout")

    mcp = FakeMCP()
    client = ErrorClient()
    aggregate.register(mcp, client, make_config())

    result = json.loads(
        mcp.tools["es_aggregate"](
            index="logs-*",
            aggs='{"levels": {"terms": {"field": "level"}}}',
            time_field="@timestamp",
            start_time="2026-04-24T00:00:00",
            end_time="2026-04-24T01:00:00",
        )
    )

    assert result["error"]["type"] == "es_error"


# --- es_mapping ---

def test_es_mapping_rejects_wildcard_or_comma_index():
    mcp = FakeMCP()
    client = FakeClient()
    mapping.register(mcp, client)

    wildcard_result = json.loads(mcp.tools["es_mapping"]("logs-*"))
    comma_result = json.loads(mcp.tools["es_mapping"]("logs-1,logs-2"))

    assert wildcard_result["error"]["type"] == "invalid_index"
    assert comma_result["error"]["type"] == "invalid_index"
    assert client.last_mapping is None


def test_es_mapping_blocks_internal_index():
    mcp = FakeMCP()
    client = FakeClient()
    mapping.register(mcp, client)

    result = json.loads(mcp.tools["es_mapping"](".security-7"))

    assert result["error"]["type"] == "guard_error"
    assert "internal index" in result["error"]["message"]


def test_es_mapping_es_error_returns_structured_error():
    class ErrorClient(FakeClient):
        def get_mapping(self, index):
            raise ConnectionError("not found")

    mcp = FakeMCP()
    client = ErrorClient()
    mapping.register(mcp, client)

    result = json.loads(mcp.tools["es_mapping"]("nonexistent"))

    assert result["error"]["type"] == "es_error"


# --- es_indices ---

def test_es_indices_requires_pattern_before_querying_client():
    mcp = FakeMCP()
    client = FakeClient()
    indices.register(mcp, client)

    result = json.loads(mcp.tools["es_indices"]())

    assert result["error"]["type"] == "clarification_required"
    assert "索引" in result["error"]["question"]
    assert client.last_indices is None


def test_es_indices_all_indices_pattern_passes_through_to_client():
    mcp = FakeMCP()
    client = FakeClient()
    indices.register(mcp, client)

    result = json.loads(mcp.tools["es_indices"]("*"))

    assert result["message"] == "No indices found"
    assert result["requested_pattern"] == "*"
    assert client.last_indices == "*"


def test_es_indices_empty_result_returns_message_and_empty_list():
    mcp = FakeMCP()
    client = FakeClient()
    indices.register(mcp, client)

    result = json.loads(mcp.tools["es_indices"]("logs-*"))

    assert result["message"] == "No indices found"
    assert result["indices"] == []


def test_es_indices_non_empty_result_sorted_by_index_name_ascending():
    class IndicesClient(FakeClient):
        def cat_indices(self, pattern):
            self.last_indices = pattern
            self.indices_calls.append(pattern)
            return [
                {"index": "logs-b", "docs.count": "10", "store.size": "5kb"},
                {"index": "logs-a", "docs.count": "20", "store.size": "10kb"},
            ]

    mcp = FakeMCP()
    client = IndicesClient()
    indices.register(mcp, client)

    result = json.loads(mcp.tools["es_indices"]("logs-*"))

    assert result["total"] == 2
    assert result["matched_by"] == "pattern"
    assert result["needs_confirmation"] is False
    names = [i["index"] for i in result["indices"]]
    assert names == ["logs-a", "logs-b"]


def test_es_indices_accepts_json_string_response():
    class JsonStringClient(FakeClient):
        def cat_indices(self, pattern):
            self.last_indices = pattern
            self.indices_calls.append(pattern)
            return '[{"index":"logs-a","docs.count":"20","store.size":"10kb"}]'

    mcp = FakeMCP()
    client = JsonStringClient()
    indices.register(mcp, client)

    result = json.loads(mcp.tools["es_indices"]("logs-*"))

    assert result["total"] == 1
    assert result["indices"][0]["index"] == "logs-a"
    assert result["indices"][0]["docs_count"] == "20"


def test_es_indices_accepts_plain_cat_text_response():
    class PlainTextClient(FakeClient):
        def cat_indices(self, pattern):
            self.last_indices = pattern
            self.indices_calls.append(pattern)
            return "logs-a 20 10kb\nlogs-b 30 15kb\n"

    mcp = FakeMCP()
    client = PlainTextClient()
    indices.register(mcp, client)

    result = json.loads(mcp.tools["es_indices"]("logs-*"))

    assert result["total"] == 2
    assert [idx["index"] for idx in result["indices"]] == ["logs-a", "logs-b"]
    assert result["indices"][1]["store_size"] == "15kb"


def test_es_indices_exact_match_does_not_try_wildcard_fallback():
    class ExactClient(FakeClient):
        def cat_indices(self, pattern):
            self.last_indices = pattern
            self.indices_calls.append(pattern)
            if pattern == "jijinslb_all":
                return [{"index": "jijinslb_all", "docs.count": "10", "store.size": "5kb"}]
            return []

    mcp = FakeMCP()
    client = ExactClient()
    indices.register(mcp, client)

    result = json.loads(mcp.tools["es_indices"]("jijinslb_all"))

    assert client.indices_calls == ["jijinslb_all"]
    assert result["matched_by"] == "exact"
    assert result["needs_confirmation"] is False
    assert result["indices"][0]["index"] == "jijinslb_all"


def test_es_indices_exact_miss_returns_wildcard_candidates_for_confirmation():
    class FallbackClient(FakeClient):
        def cat_indices(self, pattern):
            self.last_indices = pattern
            self.indices_calls.append(pattern)
            if pattern == "jijinslb_all*":
                return [
                    {"index": "jijinslb_all-2026.04.24", "docs.count": "10", "store.size": "5kb"},
                    {"index": "jijinslb_all-2026.04.25", "docs.count": "20", "store.size": "10kb"},
                ]
            return []

    mcp = FakeMCP()
    client = FallbackClient()
    indices.register(mcp, client)

    result = json.loads(mcp.tools["es_indices"]("jijinslb_all"))

    assert client.indices_calls == ["jijinslb_all", "jijinslb_all*"]
    assert result["matched_by"] == "wildcard_fallback"
    assert result["needs_confirmation"] is True
    assert result["fallback_pattern"] == "jijinslb_all*"
    assert [idx["index"] for idx in result["indices"]] == [
        "jijinslb_all-2026.04.24",
        "jijinslb_all-2026.04.25",
    ]


def test_es_indices_pattern_passed_through_to_client():
    mcp = FakeMCP()
    client = FakeClient()
    indices.register(mcp, client)

    mcp.tools["es_indices"]("order-*")

    assert client.last_indices == "order-*"


def test_es_indices_blocks_internal_pattern():
    mcp = FakeMCP()
    client = FakeClient()
    indices.register(mcp, client)

    result = json.loads(mcp.tools["es_indices"](".kibana*"))

    assert result["error"]["type"] == "guard_error"
    assert "internal index" in result["error"]["message"]


def test_es_indices_es_error_returns_structured_error():
    class ErrorClient(FakeClient):
        def cat_indices(self, pattern):
            raise ConnectionError("refused")

    mcp = FakeMCP()
    client = ErrorClient()
    indices.register(mcp, client)

    result = json.loads(mcp.tools["es_indices"]("logs-*"))

    assert result["error"]["type"] == "es_error"


# --- es_field_values ---

def test_es_field_values_returns_values():
    class ValuesClient(FakeClient):
        def search(self, index, body):
            return {
                "hits": {"total": {"value": 100}},
                "aggregations": {
                    "values": {
                        "buckets": [
                            {"key": "order-service", "doc_count": 50},
                            {"key": "pay-service", "doc_count": 30},
                        ]
                    }
                },
            }

    mcp = FakeMCP()
    client = ValuesClient()
    field_values.register(mcp, client, make_config())

    result = json.loads(
        mcp.tools["es_field_values"](
            index="logs-*",
            field="serviceName.keyword",
            time_field="@timestamp",
            start_time="2026-04-24T00:00:00",
            end_time="2026-04-24T01:00:00",
        )
    )

    assert result["field"] == "serviceName.keyword"
    assert result["total_unique"] == 2
    assert result["values"][0]["value"] == "order-service"


def test_es_field_values_blocks_internal_index():
    mcp = FakeMCP()
    client = FakeClient()
    field_values.register(mcp, client, make_config())

    result = json.loads(
        mcp.tools["es_field_values"](
            index=".kibana",
            field="type.keyword",
            time_field="@timestamp",
            start_time="2026-04-24T00:00:00",
            end_time="2026-04-24T01:00:00",
        )
    )

    assert result["error"]["type"] == "guard_error"


# --- es_server_time ---

def test_es_server_time_uses_config_timezone_offset_hours():
    mcp = FakeMCP()
    server_time.register(mcp, make_config(timezone_offset_hours=9))

    result = json.loads(mcp.tools["es_server_time"]())

    assert result["timezone"] == "UTC+9"
    assert result["current_time_display"].endswith(" UTC+9")


def test_queried_time_range_displays_user_timezone_for_utc_input():
    result = build_queried_time_range(
        "2026-04-29T02:00:00Z",
        "2026-04-29T02:30:00Z",
        {
            "gte": "2026-04-29T02:00:00.000Z",
            "lte": "2026-04-29T02:30:00.000Z",
        },
        8,
    )

    assert result["start"] == "2026-04-29T10:00:00+08:00"
    assert result["end"] == "2026-04-29T10:30:00+08:00"
    assert result["start_display"] == "2026-04-29 10:00:00 UTC+8"
    assert result["end_display"] == "2026-04-29 10:30:00 UTC+8"
    assert result["input_start"] == "2026-04-29T02:00:00Z"
    assert result["utc_start"] == "2026-04-29T02:00:00.000Z"
