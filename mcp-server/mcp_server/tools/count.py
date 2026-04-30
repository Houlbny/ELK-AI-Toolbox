import json
from typing import Optional, Union

from mcp_server.es_client import ElkClient
from mcp_server.guards import (
    GuardError,
    inject_time_filter,
    resolve_time_range,
    validate_index,
    validate_time_range,
)
from mcp_server.tools.errors import build_queried_time_range, es_error, guard_error, json_parse_error
from mcp_server.tools.parse import parse_json_like


def register(mcp, client: ElkClient, config):
    @mcp.tool()
    def es_count(
        index: str,
        query: Optional[Union[dict, str]] = None,
        time_field: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        relative_minutes: Optional[int] = None,
    ) -> str:
        """统计匹配文档数量。

        轻量级工具，用于快速了解数据规模。适合在执行复杂搜索或聚合前
        先确认目标索引在时间范围内是否有数据。如果无业务条件基线 count 为 0，
        通常无需再调用 es_search 或 es_aggregate。

        Args:
            index: 索引名或模式，如 "order-service-*"
            query: ES DSL query，优先传 JSON 对象，如 {"term": {"level": "ERROR"}}。
                如果客户端只能传字符串，必须是合法 JSON。不传则统计全部文档。
            time_field: 时间字段名，如 "@timestamp"。通过 es_mapping 获取，不要猜测。
            start_time: 起始时间 ISO 格式，如 "2026-04-24T00:00:00"。相对时间查询可不传。
            end_time: 结束时间 ISO 格式，如 "2026-04-24T23:59:59"。相对时间查询可不传。
            relative_minutes: 最近 N 分钟。用户说“过去半小时/最近30分钟”时传 30，由服务端用当前时间计算。
        """
        try:
            validate_index(index)
        except GuardError as error:
            return guard_error(error)

        has_time_filter = bool(relative_minutes is not None or start_time or end_time)
        if has_time_filter and not time_field:
            return guard_error(GuardError("time_field is required when using a time range"))

        if has_time_filter:
            try:
                start_time, end_time = resolve_time_range(
                    start_time,
                    end_time,
                    relative_minutes,
                    config.timezone_offset_hours,
                )
                validate_time_range(start_time, end_time, config.max_time_range_days)
            except GuardError as error:
                return guard_error(error)

        parsed_query = {}
        if query:
            try:
                parsed_query = parse_json_like(query, "query")
            except ValueError as error:
                return json_parse_error("query", str(error))

        utc_range = None
        if has_time_filter:
            parsed_query, utc_range = inject_time_filter(parsed_query, time_field, start_time, end_time, config.timezone_offset_hours)

        body = {"query": parsed_query} if parsed_query else None

        try:
            count = client.count(index, body)
        except Exception as error:
            return es_error(error)

        result_data = {"index": index, "count": count}
        if utc_range:
            result_data["queried_time_range"] = build_queried_time_range(
                start_time, end_time, utc_range, config.timezone_offset_hours,
                empty_result=count == 0,
            )

        return json.dumps(result_data, ensure_ascii=False)
