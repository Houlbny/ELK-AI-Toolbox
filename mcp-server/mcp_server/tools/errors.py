"""统一的错误响应格式，所有工具共享。返回 JSON 字符串供 MCP 调用方解析。"""

import json
from datetime import datetime, timedelta, timezone


def _utc_to_user_datetime(value: str, timezone_offset_hours: int) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    user_tz = timezone(timedelta(hours=timezone_offset_hours))
    return dt.astimezone(user_tz)


def _format_display_time(dt: datetime, timezone_label: str) -> str:
    return f"{dt.strftime('%Y-%m-%d %H:%M:%S')} {timezone_label}"


def guard_error(error: Exception) -> str:
    """护栏校验失败（如时间范围超限、索引非法）。"""
    return json.dumps(
        {"error": {"type": "guard_error", "message": str(error)}},
        ensure_ascii=False,
    )


def json_parse_error(field: str, message: str) -> str:
    """用户传入的 JSON 参数解析失败。"""
    return json.dumps(
        {
            "error": {
                "type": "invalid_json",
                "field": field,
                "message": message,
                "hint": f"请直接传 JSON 对象而非字符串。正确示例: {field}: {{\"term\": {{\"level\": \"ERROR\"}}}}",
            }
        },
        ensure_ascii=False,
    )


def es_error(error: Exception) -> str:
    """ES 查询执行异常。"""
    return json.dumps(
        {"error": {"type": "es_error", "message": str(error)}},
        ensure_ascii=False,
    )


def build_queried_time_range(
    start_time: str,
    end_time: str,
    utc_range: dict[str, str],
    timezone_offset_hours: int,
    *,
    empty_result: bool = False,
) -> dict:
    """构建实际查询的时间范围信息，始终附加到响应中供用户复查。"""
    tz_label = f"UTC{timezone_offset_hours:+d}"
    start = _utc_to_user_datetime(utc_range["gte"], timezone_offset_hours)
    end = _utc_to_user_datetime(utc_range["lte"], timezone_offset_hours)
    info: dict = {
        "start": start.isoformat(timespec="seconds"),
        "end": end.isoformat(timespec="seconds"),
        "timezone": tz_label,
        "start_display": _format_display_time(start, tz_label),
        "end_display": _format_display_time(end, tz_label),
        "input_start": start_time,
        "input_end": end_time,
        "utc_start": utc_range["gte"],
        "utc_end": utc_range["lte"],
    }
    if empty_result:
        info["hint"] = (
            f"查询时间已按 {tz_label} 展示为完整日期时间；"
            "utc_start/utc_end 是实际提交给 ES 的 UTC 范围。"
        )
    return info


def clarification_required(message: str, question: str) -> str:
    """缺少关键上下文，需要模型先向用户追问。"""
    return json.dumps(
        {
            "error": {
                "type": "clarification_required",
                "message": message,
                "question": question,
            }
        },
        ensure_ascii=False,
    )
