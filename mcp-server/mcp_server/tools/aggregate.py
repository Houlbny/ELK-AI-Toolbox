import json
from typing import Optional, Union

from mcp_server.config import ElkConfig
from mcp_server.es_client import ElkClient
from mcp_server.guards import (
    GuardError,
    clamp_size,
    inject_time_filter,
    resolve_time_range,
    validate_index,
    validate_time_range,
)
from mcp_server.tools.errors import build_queried_time_range, es_error, guard_error, json_parse_error
from mcp_server.tools.parse import parse_json_like


def _truncate_buckets(agg_result: dict, max_buckets: int) -> dict:
    """递归截断聚合结果中超出上限的 buckets，防止返回数据过大。"""
    truncated = {}
    for key, value in agg_result.items():
        if isinstance(value, dict):
            if "buckets" in value:
                buckets = value["buckets"]
                if isinstance(buckets, list) and len(buckets) > max_buckets:
                    value = {**value, "buckets": buckets[:max_buckets], "_truncated": True}
            truncated[key] = _truncate_buckets(value, max_buckets)
        else:
            truncated[key] = value
    return truncated


def register(mcp, client: ElkClient, config: ElkConfig):
    @mcp.tool()
    def es_aggregate(
        index: str,
        aggs: Union[dict, str],
        time_field: str,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        relative_minutes: Optional[int] = None,
        query: Optional[Union[dict, str]] = None,
        size: Optional[int] = None,
    ) -> str:
        """执行 ES 聚合查询。强制要求时间范围。Buckets 上限由配置控制。

        用于统计分析，如 Top N、按时间分布、错误率等。调用前请确保已通过 es_mapping 确认字段名和类型。
        aggs 参数必须是合法的 ES aggregation DSL。如果返回空聚合结果，先检查字段名是否正确，
        不要反复调用——同一问题最多调用 2 次。

        完整入参示例：
        {
          "index": "jijinslb_all-*",
          "aggs": {"avg_response_time": {"avg": {"field": "time_request"}}},
          "time_field": "@timestamp",
          "relative_minutes": 30,
          "query": {"match": {"http_url": "fn-api.1234567.com.cn"}}
        }

        Args:
            index: 索引名或模式，如 "order-service-2026.04.*"
            aggs: ES aggregation DSL，优先传 JSON 对象。
                如果客户端只能传字符串，必须是合法 JSON object。
                正确: {"avg_time": {"avg": {"field": "request_time"}}}
                错误: '{"avg_time": ...}'
                只放聚合定义，不要把 time_field、start_time、end_time 或 query 放进 aggs。
            time_field: 时间字段名，如 "@timestamp"。通过 es_mapping 获取，不要猜测。
            start_time: 起始时间 ISO 格式。相对时间查询可不传。
            end_time: 结束时间 ISO 格式。相对时间查询可不传。
            relative_minutes: 最近 N 分钟。用户说“过去半小时/最近30分钟”时传 30，由服务端用当前时间计算。
                如果传入该参数，将忽略 start_time/end_time，避免模型自行计算时间。
            query: 可选的过滤条件，优先传 JSON 对象，如 {"term": {"level": "ERROR"}}。
                如果客户端只能传字符串，必须是合法 JSON object。不传则不过滤。
            size: 文档返回数（int），默认 0（只返回聚合结果）
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
            clamped_size = clamp_size(size, config.max_results, default=0)
        except GuardError as error:
            return guard_error(error)

        if query:
            try:
                parsed_query = parse_json_like(query, "query")
            except ValueError as error:
                return json_parse_error("query", str(error))
        else:
            parsed_query = {}

        try:
            parsed_aggs = parse_json_like(aggs, "aggs")
        except ValueError as error:
            return json_parse_error("aggs", str(error))

        final_query, utc_range = inject_time_filter(parsed_query, time_field, start_time, end_time, config.timezone_offset_hours)

        body: dict = {
            "query": final_query,
            "aggs": parsed_aggs,
            "size": clamped_size,
            "timeout": f"{config.timeout_seconds}s",
        }

        try:
            result = client.search(index, body)
        except Exception as error:
            return es_error(error)

        aggregations = result.get("aggregations", {})
        aggregations = _truncate_buckets(aggregations, config.max_buckets)

        hits_total = result.get("hits", {}).get("total", {})
        total_value = hits_total.get("value", 0) if isinstance(hits_total, dict) else hits_total

        result_data = {"total_matched": total_value, "aggregations": aggregations}
        result_data["queried_time_range"] = build_queried_time_range(
            start_time, end_time, utc_range, config.timezone_offset_hours,
            empty_result=total_value == 0,
        )

        return json.dumps(result_data, ensure_ascii=False, indent=2, default=str)
