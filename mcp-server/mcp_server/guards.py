"""安全护栏模块。

对用户输入做校验和约束：时间范围限制、结果数量截断、内部索引访问拦截、自动注入时间过滤。
"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import re
from typing import Any, Optional


class GuardError(Exception):
    """护栏校验失败时抛出，消息会直接返回给调用方。"""
    pass


def _parse_datetime(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"

    try:
        return datetime.fromisoformat(text)
    except ValueError as exc:
        match = re.match(
            r"^(\d{4}-\d{2}-\d{2})[T ]24:00(?::00(?:\.0{1,6})?)?([+-]\d{2}:\d{2})?$",
            text,
        )
        if not match:
            raise exc

        date_part, tz_part = match.groups()
        normalized = f"{date_part}T00:00:00{tz_part or ''}"
        return datetime.fromisoformat(normalized) + timedelta(days=1)


def validate_time_range(start_time: str, end_time: str, max_days: int) -> None:
    try:
        start = _parse_datetime(start_time)
        end = _parse_datetime(end_time)
    except (TypeError, ValueError) as exc:
        raise GuardError(
            "Invalid datetime format for start_time/end_time; expected ISO 8601 datetime string"
        ) from exc

    try:
        if start >= end:
            raise GuardError("start_time must be before end_time")

        delta = end - start
    except TypeError as exc:
        raise GuardError(
            "Cannot compare mixed aware/naive datetimes; use consistent timezone information"
        ) from exc

    if delta > timedelta(days=max_days):
        raise GuardError(
            f"Time range ({delta.days}d) exceeds maximum allowed ({max_days}d). "
            f"Narrow down the time range."
        )


def clamp_size(size: Optional[int], max_results: int, default: int = 20) -> int:
    """将返回条数限制在 [0, max_results] 范围内。"""
    if size is None:
        return min(default, max_results)
    if size < 0:
        raise GuardError("size must be a non-negative integer")
    return min(size, max_results)


def resolve_time_range(
    start_time: Optional[str],
    end_time: Optional[str],
    relative_minutes: Optional[int],
    timezone_offset_hours: int = 0,
    now: Optional[datetime] = None,
) -> tuple[str, str]:
    """解析查询时间范围。

    relative_minutes 由 MCP 服务端本机时间计算，避免模型自行计算“过去半小时”等相对时间。
    如果提供 relative_minutes，则忽略 start_time/end_time，确保相对时间始终以服务端当前时间为准。
    """
    if relative_minutes is not None:
        if not isinstance(relative_minutes, int):
            raise GuardError("relative_minutes must be a positive integer")
        if relative_minutes <= 0:
            raise GuardError("relative_minutes must be a positive integer")

        local_tz = timezone(timedelta(hours=timezone_offset_hours))
        if now is None:
            end = datetime.now(local_tz)
        elif now.tzinfo is None:
            end = now.replace(tzinfo=local_tz)
        else:
            end = now.astimezone(local_tz)
        start = end - timedelta(minutes=relative_minutes)
        return start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")

    if not start_time or not end_time:
        raise GuardError("start_time and end_time are required unless relative_minutes is provided")

    return start_time, end_time


def validate_index(index: str) -> None:
    """禁止访问以 "." 开头的内部索引（如 .kibana, .security）。"""
    for part in index.split(","):
        name = part.strip()
        if name.startswith("."):
            raise GuardError(
                f"Access to internal index {name!r} is not allowed"
            )


def _to_utc_iso(time_str: str, offset_hours: int) -> str:
    """将可能不带时区的时间字符串转换为 UTC ISO 格式。

    如果已带时区信息（Z 或 +HH:MM），保持原样。
    如果不带时区信息，视为 offset_hours 指定的时区并转换为 UTC。
    """
    dt = _parse_datetime(time_str)
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    local_tz = timezone(timedelta(hours=offset_hours))
    dt = dt.replace(tzinfo=local_tz)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def inject_time_filter(
    query: dict[str, Any],
    time_field: str,
    start_time: str,
    end_time: str,
    timezone_offset_hours: int = 0,
) -> tuple[dict[str, Any], dict[str, str]]:
    """将时间范围作为 filter 注入到用户 query 中，确保所有查询都受时间约束。

    Returns:
        (final_query, utc_range) 其中 utc_range = {"gte": ..., "lte": ...} 为实际查询的 UTC 时间。
    """
    gte = _to_utc_iso(start_time, timezone_offset_hours)
    lte = _to_utc_iso(end_time, timezone_offset_hours)
    utc_range = {"gte": gte, "lte": lte}
    time_range = {"range": {time_field: {"gte": gte, "lte": lte}}}

    if not query:
        return {"bool": {"must": [], "filter": [time_range]}}, utc_range

    if "bool" in query:
        result = deepcopy(query)
        bool_query = result["bool"]
        filters = bool_query.get("filter", [])
        if isinstance(filters, dict):
            filters = [filters]
        else:
            filters = list(filters)
        filters.append(time_range)
        bool_query["filter"] = filters
        return result, utc_range

    return {"bool": {"must": [query], "filter": [time_range]}}, utc_range
