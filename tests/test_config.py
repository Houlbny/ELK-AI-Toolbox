import os
import pytest


def test_default_config(monkeypatch):
    monkeypatch.setenv("ELK_HOST", "http://localhost:9200")
    monkeypatch.setenv("ELK_USERNAME", "elastic")
    monkeypatch.setenv("ELK_PASSWORD", "changeme")

    from mcp_server.config import load_config

    cfg = load_config()
    assert cfg.host == "http://localhost:9200"
    assert cfg.username == "elastic"
    assert cfg.password == "changeme"
    assert cfg.mode == "elasticsearch"
    assert cfg.timeout_seconds == 30
    assert cfg.max_results == 50
    assert cfg.max_time_range_days == 7
    assert cfg.max_buckets == 20
    assert cfg.verify_certs is True


def test_kibana_mode(monkeypatch):
    monkeypatch.setenv("ELK_HOST", "http://kibana:5601")
    monkeypatch.setenv("ELK_USERNAME", "user")
    monkeypatch.setenv("ELK_PASSWORD", "pass")
    monkeypatch.setenv("ELK_MODE", "kibana")

    from mcp_server.config import load_config

    cfg = load_config()
    assert cfg.mode == "kibana"


def test_missing_host_raises(monkeypatch):
    monkeypatch.delenv("ELK_HOST", raising=False)
    monkeypatch.delenv("ELK_USERNAME", raising=False)
    monkeypatch.delenv("ELK_PASSWORD", raising=False)

    from mcp_server.config import load_config

    with pytest.raises(ValueError, match="ELK_HOST"):
        load_config()


def test_custom_limits(monkeypatch):
    monkeypatch.setenv("ELK_HOST", "http://localhost:9200")
    monkeypatch.setenv("ELK_USERNAME", "elastic")
    monkeypatch.setenv("ELK_PASSWORD", "pass")
    monkeypatch.setenv("ELK_MAX_RESULTS", "100")
    monkeypatch.setenv("ELK_MAX_TIME_RANGE", "14d")
    monkeypatch.setenv("ELK_TIMEOUT", "60s")
    monkeypatch.setenv("ELK_MAX_BUCKETS", "50")

    from mcp_server.config import load_config

    cfg = load_config()
    assert cfg.max_results == 100
    assert cfg.max_time_range_days == 14
    assert cfg.timeout_seconds == 60
    assert cfg.max_buckets == 50


def test_invalid_mode_raises(monkeypatch):
    monkeypatch.setenv("ELK_HOST", "http://localhost:9200")
    monkeypatch.setenv("ELK_USERNAME", "elastic")
    monkeypatch.setenv("ELK_PASSWORD", "pass")
    monkeypatch.setenv("ELK_MODE", "invalid")

    from mcp_server.config import load_config

    with pytest.raises(ValueError, match="ELK_MODE"):
        load_config()


def test_invalid_max_time_range_format_raises(monkeypatch):
    monkeypatch.setenv("ELK_HOST", "http://localhost:9200")
    monkeypatch.setenv("ELK_USERNAME", "elastic")
    monkeypatch.setenv("ELK_PASSWORD", "pass")
    monkeypatch.setenv("ELK_MAX_TIME_RANGE", "7")

    from mcp_server.config import load_config

    with pytest.raises(ValueError, match="ELK_MAX_TIME_RANGE"):
        load_config()


def test_invalid_max_results_non_number_raises(monkeypatch):
    monkeypatch.setenv("ELK_HOST", "http://localhost:9200")
    monkeypatch.setenv("ELK_USERNAME", "elastic")
    monkeypatch.setenv("ELK_PASSWORD", "pass")
    monkeypatch.setenv("ELK_MAX_RESULTS", "abc")

    from mcp_server.config import load_config

    with pytest.raises(ValueError, match="ELK_MAX_RESULTS"):
        load_config()


def test_invalid_max_results_non_positive_raises(monkeypatch):
    monkeypatch.setenv("ELK_HOST", "http://localhost:9200")
    monkeypatch.setenv("ELK_USERNAME", "elastic")
    monkeypatch.setenv("ELK_PASSWORD", "pass")
    monkeypatch.setenv("ELK_MAX_RESULTS", "0")

    from mcp_server.config import load_config

    with pytest.raises(ValueError, match="ELK_MAX_RESULTS"):
        load_config()


def test_invalid_timeout_format_raises(monkeypatch):
    monkeypatch.setenv("ELK_HOST", "http://localhost:9200")
    monkeypatch.setenv("ELK_USERNAME", "elastic")
    monkeypatch.setenv("ELK_PASSWORD", "pass")
    monkeypatch.setenv("ELK_TIMEOUT", "30")

    from mcp_server.config import load_config

    with pytest.raises(ValueError, match="ELK_TIMEOUT"):
        load_config()


def test_invalid_timeout_non_positive_raises(monkeypatch):
    monkeypatch.setenv("ELK_HOST", "http://localhost:9200")
    monkeypatch.setenv("ELK_USERNAME", "elastic")
    monkeypatch.setenv("ELK_PASSWORD", "pass")
    monkeypatch.setenv("ELK_TIMEOUT", "0s")

    from mcp_server.config import load_config

    with pytest.raises(ValueError, match="ELK_TIMEOUT"):
        load_config()


def test_invalid_max_time_range_non_positive_raises(monkeypatch):
    monkeypatch.setenv("ELK_HOST", "http://localhost:9200")
    monkeypatch.setenv("ELK_USERNAME", "elastic")
    monkeypatch.setenv("ELK_PASSWORD", "pass")
    monkeypatch.setenv("ELK_MAX_TIME_RANGE", "0d")

    from mcp_server.config import load_config

    with pytest.raises(ValueError, match="ELK_MAX_TIME_RANGE"):
        load_config()


def test_verify_certs_false_explicit(monkeypatch):
    monkeypatch.setenv("ELK_HOST", "https://localhost:9200")
    monkeypatch.setenv("ELK_USERNAME", "elastic")
    monkeypatch.setenv("ELK_PASSWORD", "pass")
    monkeypatch.setenv("ELK_VERIFY_CERTS", "false")

    from mcp_server.config import load_config

    cfg = load_config()
    assert cfg.verify_certs is False


def test_invalid_verify_certs_raises(monkeypatch):
    monkeypatch.setenv("ELK_HOST", "https://localhost:9200")
    monkeypatch.setenv("ELK_USERNAME", "elastic")
    monkeypatch.setenv("ELK_PASSWORD", "pass")
    monkeypatch.setenv("ELK_VERIFY_CERTS", "maybe")

    from mcp_server.config import load_config

    with pytest.raises(ValueError, match="ELK_VERIFY_CERTS"):
        load_config()


def test_overrides_take_precedence_for_non_sensitive_fields(monkeypatch):
    monkeypatch.setenv("ELK_HOST", "http://localhost:9200")
    monkeypatch.setenv("ELK_USERNAME", "elastic")
    monkeypatch.setenv("ELK_PASSWORD", "pass")
    monkeypatch.setenv("ELK_MODE", "elasticsearch")
    monkeypatch.setenv("ELK_TIMEOUT", "30s")
    monkeypatch.setenv("ELK_MAX_RESULTS", "50")
    monkeypatch.setenv("ELK_MAX_TIME_RANGE", "7d")
    monkeypatch.setenv("ELK_VERIFY_CERTS", "true")

    from mcp_server.config import load_config

    cfg = load_config(
        overrides={
            "mode": "kibana",
            "timeout": "60s",
            "max_results": 20,
            "max_time_range": "14d",
            "max_buckets": 50,
            "verify_certs": "false",
        }
    )

    assert cfg.mode == "kibana"
    assert cfg.timeout_seconds == 60
    assert cfg.max_results == 20
    assert cfg.max_time_range_days == 14
    assert cfg.max_buckets == 50
    assert cfg.verify_certs is False


def test_overrides_do_not_replace_required_credentials(monkeypatch):
    monkeypatch.delenv("ELK_HOST", raising=False)
    monkeypatch.delenv("ELK_USERNAME", raising=False)
    monkeypatch.delenv("ELK_PASSWORD", raising=False)

    from mcp_server.config import load_config

    with pytest.raises(ValueError, match="ELK_HOST"):
        load_config(overrides={"timeout": "60s"})


def test_invalid_max_buckets_raises(monkeypatch):
    monkeypatch.setenv("ELK_HOST", "http://localhost:9200")
    monkeypatch.setenv("ELK_USERNAME", "elastic")
    monkeypatch.setenv("ELK_PASSWORD", "pass")
    monkeypatch.setenv("ELK_MAX_BUCKETS", "0")

    from mcp_server.config import load_config

    with pytest.raises(ValueError, match="ELK_MAX_BUCKETS"):
        load_config()
