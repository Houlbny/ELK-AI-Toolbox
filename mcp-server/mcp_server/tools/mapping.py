import json

from mcp_server.es_client import ElkClient
from mcp_server.guards import GuardError, validate_index
from mcp_server.tools.errors import es_error, guard_error


def _flatten_mapping(properties: dict, prefix: str = "") -> list[dict]:
    """将嵌套的 ES mapping 递归展平为 [{"field": "a.b.c", "type": "keyword"}, ...] 列表。"""
    fields = []
    for name, info in properties.items():
        full_name = name if not prefix else f"{prefix}.{name}"
        field_type = info.get("type", "object")
        entry = {"field": full_name, "type": field_type}
        if "format" in info:
            entry["format"] = info["format"]
        fields.append(entry)
        if "properties" in info:
            fields.extend(_flatten_mapping(info["properties"], full_name))
    return fields


def register(mcp, client: ElkClient):
    @mcp.tool()
    def es_mapping(index: str) -> str:
        """查看索引的字段结构（mapping）。返回扁平化的字段名和类型列表。

        这是构造查询前的必要步骤。使用 es_search / es_aggregate 之前，
        先用此工具确认时间字段名（如 @timestamp）和可用字段，避免猜测字段名导致查询失败。
        注意：只接受单个具体索引名，不支持通配符。

        Args:
            index: 索引名，如 "order-service-2026.04.24"
        """
        if "*" in index or "," in index:
            return json.dumps(
                {
                    "error": {
                        "type": "invalid_index",
                        "message": "index must be a single concrete index name; wildcard or comma list is not supported",
                    }
                },
                ensure_ascii=False,
            )

        try:
            validate_index(index)
        except GuardError as error:
            return guard_error(error)

        try:
            raw = client.get_mapping(index)
        except Exception as error:
            return es_error(error)

        index_data = raw.get(index)
        if index_data is None and raw:
            index_data = next(iter(raw.values()))

        props = (index_data or {}).get("mappings", {}).get("properties", {})
        fields = _flatten_mapping(props)

        return json.dumps(
            {"index": index, "field_count": len(fields), "fields": fields},
            ensure_ascii=False,
            indent=2,
        )
