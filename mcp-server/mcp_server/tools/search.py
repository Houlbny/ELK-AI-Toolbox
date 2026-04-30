import json
from json import JSONDecodeError
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


def register(mcp, client: ElkClient, config: ElkConfig):
    @mcp.tool()
    def es_search(
        index: str,
        query: Union[dict, str],
        time_field: str,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        relative_minutes: Optional[int] = None,
        sort: Optional[Union[list, dict, str]] = None,
        size: Optional[int] = None,
        source_fields: Optional[str] = None,
        from_offset: Optional[int] = None,
    ) -> str:
        """搜索 ES 文档。强制要求时间范围。

        用于检索具体日志内容。调用前请确保已通过 es_mapping 确认字段名。
        如果返回 0 条结果，先检查索引名和字段名是否正确，不要直接换参数重试。
        需要统计分布或 Top N 时，应使用 es_aggregate 而非多次 es_search。

        Args:
            index: 索引名或模式，如 "order-service-2026.04.*"
            query: ES DSL query，优先传 JSON 对象，如 {"match": {"level": "ERROR"}}。
                如果客户端只能传字符串，必须是合法 JSON。
                正确: {"match": {"level": "ERROR"}}
                错误: '{"match": {"level": "ERROR"}}'
            time_field: 时间字段名，如 "@timestamp"。通过 es_mapping 获取，不要猜测。
            start_time: 起始时间 ISO 格式，如 "2026-04-24T00:00:00"。相对时间查询可不传。
            end_time: 结束时间 ISO 格式，如 "2026-04-24T23:59:59"。相对时间查询可不传。
            relative_minutes: 最近 N 分钟。用户说“过去半小时/最近30分钟”时传 30，由服务端用当前时间计算。
                如果传入该参数，将忽略 start_time/end_time，避免模型自行计算时间。
            sort: 排序规则，优先传 JSON 数组，如 [{"@timestamp": "desc"}]。
                如果客户端只能传字符串，必须是合法 JSON array 或 object。
            size: 返回条数（int），默认 20
            source_fields: 指定返回字段，逗号分隔的字符串，如 "timestamp,level,message"
            from_offset: 分页偏移量（int）
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
            clamped_size = clamp_size(size, config.max_results)
        except GuardError as error:
            return guard_error(error)

        try:
            parsed_query = parse_json_like(query, "query")
        except ValueError as error:
            return json_parse_error("query", str(error))

        final_query, utc_range = inject_time_filter(parsed_query, time_field, start_time, end_time, config.timezone_offset_hours)

        body: dict = {
            "query": final_query,
            "size": clamped_size,
            "timeout": f"{config.timeout_seconds}s",
        }

        if sort:
            if isinstance(sort, (list, dict)):
                body["sort"] = sort
            else:
                try:
                    body["sort"] = json.loads(sort)
                except JSONDecodeError as error:
                    return json_parse_error("sort", str(error))
        else:
            body["sort"] = [{time_field: "desc"}]

        if source_fields:
            body["_source"] = [f.strip() for f in source_fields.split(",")]

        if from_offset is not None:
            body["from"] = from_offset

        try:
            result = client.search(index, body)
        except Exception as error:
            return es_error(error)

        hits = result.get("hits", {})
        total = hits.get("total", {})
        # ES 7+ 的 total 是 {"value": N, "relation": "eq"}，兼容旧版直接返回数字
        total_value = total.get("value", 0) if isinstance(total, dict) else total

        # 将 _source 展平并附上 _index/_id，方便调用方直接使用
        docs = []
        for hit in hits.get("hits", []):
            doc = {**hit.get("_source", {}), "_index": hit.get("_index", ""), "_id": hit.get("_id", "")}
            docs.append(doc)

        result_data = {"total": total_value, "returned": len(docs), "docs": docs}
        result_data["queried_time_range"] = build_queried_time_range(
            start_time, end_time, utc_range, config.timezone_offset_hours,
            empty_result=total_value == 0,
        )

        return json.dumps(result_data, ensure_ascii=False, indent=2, default=str)
