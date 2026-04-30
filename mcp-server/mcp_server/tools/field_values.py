import json
from typing import Optional, Union

from mcp_server.config import ElkConfig
from mcp_server.es_client import ElkClient
from mcp_server.guards import (
    GuardError,
    inject_time_filter,
    resolve_time_range,
    validate_index,
    validate_time_range,
)
from mcp_server.tools.errors import build_queried_time_range, es_error, guard_error


def register(mcp, client: ElkClient, config: ElkConfig):
    @mcp.tool()
    def es_field_values(
        index: str,
        field: str,
        time_field: str,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        relative_minutes: Optional[int] = None,
        size: Optional[int] = None,
        query: Optional[Union[dict, str]] = None,
    ) -> str:
        """查询某个 keyword 字段的唯一值列表（去重 Top N）。

        适合在构造精确查询前先了解字段有哪些可选值，如服务名、日志级别、主机名等。
        比手动写 es_aggregate terms 聚合更简单。字段必须是 keyword 类型，
        可通过 es_mapping 确认字段类型。

        Args:
            index: 索引名或模式，如 "order-service-2026.04.*"
            field: 要查询的字段名（必须是 keyword 类型），如 "serviceName.keyword"。
                通过 es_mapping 确认字段名和类型，keyword 字段通常带 .keyword 后缀。
            time_field: 时间字段名，如 "@timestamp"。通过 es_mapping 获取，不要猜测。
            start_time: 起始时间 ISO 格式。相对时间查询可不传。
            end_time: 结束时间 ISO 格式。相对时间查询可不传。
            relative_minutes: 最近 N 分钟。用户说“过去半小时/最近30分钟”时传 30，由服务端用当前时间计算。
            size: 返回的唯一值数量（int），默认 20
            query: 可选的过滤条件，优先传 JSON 对象，如 {"term": {"level": "ERROR"}}。
                如果客户端只能传字符串，必须是合法 JSON object。不传则不过滤。
        """
        try:
            validate_index(index)
            start_time, end_time = resolve_time_range(
                start_time,
                end_time,
                relative_minutes,
                config.timezone_offset_hours,
            )
            validate_time_range(start_time, end_time, config.max_time_range_days)
        except GuardError as error:
            return guard_error(error)

        effective_size = min(size or 20, config.max_buckets)

        from mcp_server.tools.parse import parse_json_like

        parsed_query = {}
        if query:
            try:
                parsed_query = parse_json_like(query, "query")
            except ValueError as error:
                from mcp_server.tools.errors import json_parse_error
                return json_parse_error("query", str(error))

        final_query, utc_range = inject_time_filter(parsed_query, time_field, start_time, end_time, config.timezone_offset_hours)

        body = {
            "query": final_query,
            "aggs": {
                "values": {
                    "terms": {"field": field, "size": effective_size}
                }
            },
            "size": 0,
            "timeout": f"{config.timeout_seconds}s",
        }

        try:
            result = client.search(index, body)
        except Exception as error:
            return es_error(error)

        buckets = result.get("aggregations", {}).get("values", {}).get("buckets", [])
        values = [{"value": b["key"], "count": b["doc_count"]} for b in buckets]

        result_data = {"field": field, "total_unique": len(values), "values": values}
        result_data["queried_time_range"] = build_queried_time_range(
            start_time, end_time, utc_range, config.timezone_offset_hours,
            empty_result=len(values) == 0,
        )

        return json.dumps(result_data, ensure_ascii=False, indent=2, default=str)
