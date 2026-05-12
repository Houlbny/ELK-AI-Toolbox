"""ELK MCP Server 入口。

解析命令行参数，初始化 ES 客户端，注册所有 MCP 工具，支持 stdio 和 sse 传输模式。
"""

import argparse
import atexit
import logging

from mcp.server.fastmcp import FastMCP

from mcp_server.config import load_config
from mcp_server.es_client import ElkClient
from mcp_server.tools import aggregate, count, field_values, indices, mapping, search, server_time

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)


MCP_INSTRUCTIONS = """ELK 日志查询工具集，提供索引发现、字段结构查看、日志搜索、计数和聚合统计能力。

## 全局流程
1. 先确认索引范围。执行业务查询前需要明确索引名、索引通配模式、Kibana 数据视图名或业务系统名；如果缺失，先问用户。用户明确要求列出/探索索引时，可以调用 es_indices(pattern="*")，但后续查询应尽量收窄到具体模式。
2. 用户说“xxx 索引”时，先用 es_indices(pattern="xxx") 精确确认；如果返回 needs_confirmation=true，必须让用户确认候选后再继续。用户说“xxx 视图/数据视图/index pattern”时，用 es_indices(pattern="xxx*")。
3. 构造查询前先用 es_mapping(index="具体索引名") 确认时间字段、条件字段和字段类型。es_mapping 只接受具体索引；按天切分的日志在 es_search/es_count/es_aggregate/es_field_values 中优先使用通配模式（如 xxx-*），不要把查询固定到单个日期索引。
4. 业务字段必须来自 mapping。字段或取值不确定时，在同一 index 和同一 time range 内用 es_field_values 或小样本 es_search 验证，不要凭空造字段名。
5. 如果带业务条件的查询为空，固定原索引和原时间范围，先去掉业务条件做 es_count 基线。基线 count > 0 时逐个隔离字段、取值和匹配方式；只有基线 count = 0 或用户明确同意时，才考虑扩大时间范围。

## 时间策略
- 最近/过去 N 分钟、过去半小时、最近一小时：直接给查询工具传 relative_minutes（如 30 或 60），不要自行计算 start_time/end_time。
- 今天、昨天、刚发布、发布前后窗口等需要当前日期/时间的场景：调用 es_server_time 后再计算绝对 start_time/end_time。
- 用户给出绝对时间时直接使用；不要向用户询问当前时间，也不要回答不知道当前时间。

## 参数规范
- query/aggs/sort 优先传 JSON object/array；如果客户端只能传字符串，必须是合法 JSON。
- aggs 只放聚合定义；time_field、start_time、end_time、relative_minutes、query 都作为工具顶层参数传入。
- time_field 必须来自 es_mapping。keyword 字段用 term 精确匹配，text 字段用 match/match_phrase；聚合和排序只用 keyword/numeric/date 字段。

## 输出规范
- 最终回复必须展示完整日期 + 时间 + 时区，优先使用工具返回的 queried_time_range.start_display/end_display。
- 日志字段若是 UTC（Z 或 +00:00），展示给用户前转换到 queried_time_range.timezone；不要只写 HH:MM:SS 或“几分钟前”。
"""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ELK MCP server")
    parser.add_argument("--mode", choices=["elasticsearch", "kibana"])
    parser.add_argument("--timeout")
    parser.add_argument("--max-results", type=int)
    parser.add_argument("--max-time-range")
    parser.add_argument("--max-buckets", type=int)
    parser.add_argument("--verify-certs", choices=["true", "false"])
    parser.add_argument("--kibana-space", default=None, help="Kibana space ID (e.g. 'jijinslb')")
    parser.add_argument("--timezone-offset", type=int, default=None, help="UTC offset hours (default 8 for Beijing)")
    parser.add_argument("--transport", choices=["stdio", "sse"], default="stdio", help="Transport protocol (default: stdio)")
    parser.add_argument("--host", default="0.0.0.0", help="SSE server bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="SSE server bind port (default: 8000)")
    return parser.parse_args(argv)


def build_overrides(args: argparse.Namespace) -> dict:
    overrides = {}
    if args.mode is not None:
        overrides["mode"] = args.mode
    if args.timeout is not None:
        overrides["timeout"] = args.timeout
    if args.max_results is not None:
        overrides["max_results"] = args.max_results
    if args.max_time_range is not None:
        overrides["max_time_range"] = args.max_time_range
    if args.max_buckets is not None:
        overrides["max_buckets"] = args.max_buckets
    if args.verify_certs is not None:
        overrides["verify_certs"] = args.verify_certs
    if args.kibana_space is not None:
        overrides["kibana_space"] = args.kibana_space
    if args.timezone_offset is not None:
        overrides["timezone_offset"] = str(args.timezone_offset)
    return overrides


def create_mcp(client: ElkClient, config, *, host: str = "127.0.0.1", port: int = 8000) -> FastMCP:
    """创建 MCP 实例并注册所有工具（索引、映射、计数、搜索、聚合、字段值）。"""
    mcp = FastMCP("elk", instructions=MCP_INSTRUCTIONS, host=host, port=port)
    indices.register(mcp, client, config)
    mapping.register(mcp, client)
    count.register(mcp, client, config)
    search.register(mcp, client, config)
    aggregate.register(mcp, client, config)
    field_values.register(mcp, client, config)
    server_time.register(mcp, config)
    return mcp


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    config = load_config(overrides=build_overrides(args))
    client = ElkClient(config)
    atexit.register(client.close)
    mcp = create_mcp(client, config, host=args.host, port=args.port)
    if args.transport == "sse":
        mcp.run(transport="sse")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
