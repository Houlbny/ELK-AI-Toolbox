"""ELK MCP Server 配置模块。

从环境变量和命令行参数加载 ES 连接配置，支持参数覆盖。
"""

import os
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ElkConfig:
    """不可变的 ELK 连接配置，所有字段在创建后不可修改。"""
    mode: str
    host: str
    username: str
    password: str
    timeout_seconds: int
    max_results: int
    max_time_range_days: int
    max_buckets: int
    verify_certs: bool
    kibana_space: str = ""
    timezone_offset_hours: int = 8


def _parse_timeout(value: str) -> int:
    """解析超时时间字符串，如 "30s" -> 30"""
    m = re.match(r"^(\d+)s$", value)
    if not m:
        raise ValueError(
            f"ELK_TIMEOUT must match format '^\\d+s$' with positive seconds, got {value!r}"
        )
    seconds = int(m.group(1))
    if seconds <= 0:
        raise ValueError(
            f"ELK_TIMEOUT must be positive seconds in format '^\\d+s$', got {value!r}"
        )
    return seconds


def _parse_time_range(value: str) -> int:
    """解析时间范围字符串，如 "7d" -> 7"""
    m = re.match(r"^(\d+)d$", value)
    if not m:
        raise ValueError(
            f"ELK_MAX_TIME_RANGE must match format '^\\d+d$' with positive days, got {value!r}"
        )

    days = int(m.group(1))
    if days <= 0:
        raise ValueError(
            f"ELK_MAX_TIME_RANGE must be positive day count in format '^\\d+d$', got {value!r}"
        )
    return days


def _parse_positive_int(value: str, env_name: str) -> int:
    try:
        n = int(value)
    except ValueError as exc:
        raise ValueError(f"{env_name} must be a positive integer, got {value!r}") from exc
    if n <= 0:
        raise ValueError(f"{env_name} must be a positive integer, got {value!r}")
    return n


def _parse_bool(value: str, env_name: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{env_name} must be a boolean (true/false), got {value!r}")


def load_config(overrides: dict | None = None) -> ElkConfig:
    """加载配置：命令行参数(overrides) > 环境变量 > 默认值。"""
    values = dict(overrides or {})

    mode = values.get("mode") or os.environ.get("ELK_MODE", "elasticsearch")
    if mode not in ("elasticsearch", "kibana"):
        raise ValueError(f"ELK_MODE must be 'elasticsearch' or 'kibana', got {mode!r}")

    host = os.environ.get("ELK_HOST")
    if not host:
        raise ValueError(
            f"ELK_HOST environment variable is required (should be the {mode} URL)"
        )

    username = os.environ.get("ELK_USERNAME")
    if not username:
        raise ValueError(
            f"ELK_USERNAME environment variable is required (should be the {mode} account)"
        )

    password = os.environ.get("ELK_PASSWORD")
    if not password:
        raise ValueError(
            f"ELK_PASSWORD environment variable is required (should be the {mode} password)"
        )

    timeout_raw = values.get("timeout") or os.environ.get("ELK_TIMEOUT", "30s")
    timeout_seconds = _parse_timeout(timeout_raw)

    max_results_raw = values.get("max_results")
    max_results_value = (
        str(max_results_raw)
        if max_results_raw is not None
        else os.environ.get("ELK_MAX_RESULTS", "50")
    )
    max_results = _parse_positive_int(max_results_value, "ELK_MAX_RESULTS")

    max_buckets_raw = values.get("max_buckets")
    max_buckets_value = (
        str(max_buckets_raw)
        if max_buckets_raw is not None
        else os.environ.get("ELK_MAX_BUCKETS", "20")
    )
    max_buckets = _parse_positive_int(max_buckets_value, "ELK_MAX_BUCKETS")

    max_time_range = values.get("max_time_range") or os.environ.get("ELK_MAX_TIME_RANGE", "7d")
    verify_certs_raw = values.get("verify_certs")
    verify_certs_value = (
        str(verify_certs_raw)
        if verify_certs_raw is not None
        else os.environ.get("ELK_VERIFY_CERTS", "true")
    )

    kibana_space = values.get("kibana_space") or os.environ.get("ELK_KIBANA_SPACE", "")
    tz_offset_raw = values.get("timezone_offset") or os.environ.get("ELK_TIMEZONE_OFFSET", "8")
    try:
        timezone_offset_hours = int(tz_offset_raw)
    except ValueError as exc:
        raise ValueError(f"ELK_TIMEZONE_OFFSET must be an integer, got {tz_offset_raw!r}") from exc

    return ElkConfig(
        mode=mode,
        host=host,
        username=username,
        password=password,
        timeout_seconds=timeout_seconds,
        max_results=max_results,
        max_time_range_days=_parse_time_range(max_time_range),
        max_buckets=max_buckets,
        verify_certs=_parse_bool(verify_certs_value, "ELK_VERIFY_CERTS"),
        kibana_space=kibana_space,
        timezone_offset_hours=timezone_offset_hours,
    )
