import pytest
from datetime import datetime, timedelta, timezone
from mcp_server.guards import (
    validate_time_range,
    validate_index,
    clamp_size,
    inject_time_filter,
    resolve_time_range,
    GuardError,
)


def test_validate_time_range_valid():
    now = datetime.utcnow()
    start = (now - timedelta(hours=1)).isoformat()
    end = now.isoformat()
    validate_time_range(start, end, max_days=7)


def test_validate_time_range_exceeds_max():
    now = datetime.utcnow()
    start = (now - timedelta(days=10)).isoformat()
    end = now.isoformat()
    with pytest.raises(GuardError, match="exceeds maximum"):
        validate_time_range(start, end, max_days=7)


def test_validate_time_range_start_after_end():
    now = datetime.utcnow()
    start = now.isoformat()
    end = (now - timedelta(hours=1)).isoformat()
    with pytest.raises(GuardError, match="start_time must be before end_time"):
        validate_time_range(start, end, max_days=7)


def test_clamp_size_within_limit():
    assert clamp_size(20, max_results=50) == 20


def test_clamp_size_exceeds_limit():
    assert clamp_size(100, max_results=50) == 50


def test_clamp_size_none_returns_default():
    assert clamp_size(None, max_results=50, default=20) == 20


def test_clamp_size_negative_raises():
    with pytest.raises(GuardError, match="non-negative"):
        clamp_size(-1, max_results=50)


def test_resolve_time_range_uses_server_now_for_relative_minutes():
    now = datetime(2026, 4, 29, 10, 30, 15, tzinfo=timezone.utc)

    start, end = resolve_time_range(
        "2020-01-01T00:00:00",
        "2020-01-01T01:00:00",
        relative_minutes=30,
        timezone_offset_hours=8,
        now=now,
    )

    assert start == "2026-04-29T18:00:15+08:00"
    assert end == "2026-04-29T18:30:15+08:00"


def test_resolve_time_range_requires_absolute_or_relative_time():
    with pytest.raises(GuardError, match="required unless relative_minutes"):
        resolve_time_range(None, None, None)


def test_resolve_time_range_rejects_non_positive_relative_minutes():
    with pytest.raises(GuardError, match="positive integer"):
        resolve_time_range(None, None, 0)


def test_validate_time_range_invalid_datetime_raises():
    with pytest.raises(GuardError, match="Invalid datetime format"):
        validate_time_range("not-a-date", "2026-04-24T00:00:00", max_days=7)


def test_validate_time_range_accepts_24_hour_boundary():
    validate_time_range("2026-04-24T23:30:00", "2026-04-24T24:00:00", max_days=7)


def test_validate_time_range_mixed_aware_naive_raises():
    with pytest.raises(GuardError, match="mixed aware/naive"):
        validate_time_range("2026-04-24T00:00:00+00:00", "2026-04-24T01:00:00", max_days=7)


def test_inject_time_filter_empty_query():
    query = {}
    result, utc_range = inject_time_filter(query, "@timestamp", "2026-04-24T00:00:00", "2026-04-24T23:59:59")
    assert result == {
        "bool": {
            "must": [],
            "filter": [
                {"range": {"@timestamp": {"gte": "2026-04-24T00:00:00.000Z", "lte": "2026-04-24T23:59:59.000Z"}}}
            ],
        }
    }
    assert utc_range == {"gte": "2026-04-24T00:00:00.000Z", "lte": "2026-04-24T23:59:59.000Z"}


def test_inject_time_filter_with_existing_query():
    query = {"match": {"level": "ERROR"}}
    result, utc_range = inject_time_filter(query, "@timestamp", "2026-04-24T00:00:00", "2026-04-24T23:59:59")
    assert result == {
        "bool": {
            "must": [{"match": {"level": "ERROR"}}],
            "filter": [
                {"range": {"@timestamp": {"gte": "2026-04-24T00:00:00.000Z", "lte": "2026-04-24T23:59:59.000Z"}}}
            ],
        }
    }
    assert utc_range == {"gte": "2026-04-24T00:00:00.000Z", "lte": "2026-04-24T23:59:59.000Z"}


def test_inject_time_filter_normalizes_24_hour_boundary():
    result, utc_range = inject_time_filter(
        {},
        "@timestamp",
        "2026-04-24T23:30:00",
        "2026-04-24T24:00:00",
    )

    assert result["bool"]["filter"][0]["range"]["@timestamp"]["lte"] == "2026-04-25T00:00:00.000Z"
    assert utc_range["lte"] == "2026-04-25T00:00:00.000Z"


def test_inject_time_filter_with_existing_bool():
    query = {"bool": {"must": [{"term": {"status": 500}}], "filter": [{"term": {"env": "prod"}}]}}
    result, _ = inject_time_filter(query, "@timestamp", "2026-04-24T00:00:00", "2026-04-24T23:59:59")
    assert result["bool"]["filter"] == [
        {"term": {"env": "prod"}},
        {"range": {"@timestamp": {"gte": "2026-04-24T00:00:00.000Z", "lte": "2026-04-24T23:59:59.000Z"}}},
    ]
    assert result["bool"]["must"] == [{"term": {"status": 500}}]


def test_inject_time_filter_with_existing_bool_does_not_mutate_input():
    query = {"bool": {"must": [{"term": {"status": 500}}], "filter": [{"term": {"env": "prod"}}]}}

    result, _ = inject_time_filter(query, "@timestamp", "2026-04-24T00:00:00", "2026-04-24T23:59:59")

    assert query == {"bool": {"must": [{"term": {"status": 500}}], "filter": [{"term": {"env": "prod"}}]}}
    assert result is not query


# --- validate_index tests ---

def test_validate_index_allows_normal_index():
    validate_index("order-service-2026.04.*")


def test_validate_index_blocks_internal_index():
    with pytest.raises(GuardError, match="internal index"):
        validate_index(".kibana")


def test_validate_index_blocks_internal_index_in_comma_list():
    with pytest.raises(GuardError, match="internal index"):
        validate_index("logs-*, .security-7")


def test_validate_index_allows_wildcard_without_dot_prefix():
    validate_index("*")
