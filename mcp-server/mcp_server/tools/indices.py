import json
from datetime import datetime, timedelta, timezone
from json import JSONDecodeError
from typing import Any, Optional

from mcp_server.es_client import ElkClient
from mcp_server.guards import GuardError, validate_index
from mcp_server.tools.errors import clarification_required, es_error, guard_error


def _parse_cat_indices_text(text: str) -> list[dict[str, Any]]:
    rows = []
    for line in text.splitlines():
        parts = line.split()
        if not parts:
            continue
        row = {"index": parts[0]}
        if len(parts) > 1:
            row["docs.count"] = parts[1]
        if len(parts) > 2:
            row["store.size"] = parts[2]
        rows.append(row)
    return rows


def _normalize_indices_response(raw: Any) -> list[dict[str, Any]]:
    if raw is None:
        return []

    if hasattr(raw, "body"):
        return _normalize_indices_response(raw.body)

    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except JSONDecodeError:
            return _parse_cat_indices_text(text)
        return _normalize_indices_response(parsed)

    if isinstance(raw, dict):
        for key in ("indices", "body", "response", "result", "data"):
            if key in raw:
                return _normalize_indices_response(raw[key])
        if "index" in raw:
            return [raw]
        raise ValueError(f"Unexpected cat indices response object keys: {sorted(raw.keys())}")

    if isinstance(raw, (list, tuple)):
        rows = []
        for item in raw:
            rows.extend(_normalize_indices_response(item))
        return rows

    raise ValueError(f"Unexpected cat indices response type: {type(raw).__name__}")


def _format_indices(indices: list[dict[str, Any]], today_suffix: str = "") -> list[dict]:
    result = []
    for idx in indices:
        name = idx.get("index", "")
        entry = {
            "index": name,
            "docs_count": idx.get("docs.count", "0"),
            "store_size": idx.get("store.size", "0"),
        }
        if today_suffix and name.endswith(today_suffix):
            entry["is_today"] = True
        result.append(entry)
    result.sort(key=lambda x: x["index"])
    return result


def register(mcp, client: ElkClient, config=None):
    tz_offset = int(getattr(config, "timezone_offset_hours", 8)) if config else 8
    local_tz = timezone(timedelta(hours=tz_offset))

    @mcp.tool()
    def es_indices(pattern: Optional[str] = None) -> str:
        """列出 Elasticsearch 索引。返回索引名、文档数和存储大小。

        这是确认索引范围的工具。用户明确要求查看/探索索引时，可以用 pattern="*"；
        执行业务查询前仍应优先使用更窄的索引名、通配模式或 Kibana 数据视图名。

        当用户提到 Kibana「数据视图」或「视图」时，用视图名加通配符搜索，
        例如用户说「jinjinslb_all 视图」，应传 pattern="jinjinslb_all*" 来发现对应索引。
        当用户明确说「xxx 索引」时，先传 pattern="xxx" 做精确确认；如果精确索引不存在，
        本工具会自动 fallback 查询 "xxx*" 并要求模型向用户确认候选索引。

        Args:
            pattern: 索引名或匹配模式，如 "order-service" / "order-service-*" / "*"。
                不要传空值；只有用户明确要列出或探索索引时才使用 "*"。
        """
        effective_pattern = (pattern or "").strip()
        if not effective_pattern:
            return clarification_required(
                "缺少索引名、索引通配模式或 Kibana 数据视图名。",
                "请先确认要查询哪个索引/视图；如果用户只是想浏览索引，可以调用 es_indices(pattern=\"*\")。",
            )

        try:
            validate_index(effective_pattern)
        except GuardError as error:
            return guard_error(error)

        try:
            indices = _normalize_indices_response(client.cat_indices(effective_pattern))
        except Exception as error:
            return es_error(error)

        today_suffix = datetime.now(local_tz).strftime("%Y.%m.%d")

        has_wildcard = any(ch in effective_pattern for ch in "*?[")
        if indices:
            result = _format_indices(indices, today_suffix)
            return json.dumps(
                {
                    "total": len(result),
                    "matched_by": "pattern" if has_wildcard else "exact",
                    "needs_confirmation": False,
                    "today": today_suffix,
                    "indices": result,
                },
                ensure_ascii=False,
                indent=2,
            )

        if has_wildcard or "," in effective_pattern:
            return json.dumps(
                {"message": "No indices found", "requested_pattern": effective_pattern, "indices": []},
                ensure_ascii=False,
            )

        fallback_pattern = f"{effective_pattern}*"
        try:
            validate_index(fallback_pattern)
            fallback_indices = _normalize_indices_response(client.cat_indices(fallback_pattern))
        except GuardError as error:
            return guard_error(error)
        except Exception as error:
            return es_error(error)

        if not fallback_indices:
            return json.dumps(
                {
                    "message": "No indices found",
                    "requested_pattern": effective_pattern,
                    "fallback_pattern": fallback_pattern,
                    "indices": [],
                },
                ensure_ascii=False,
            )

        result = _format_indices(fallback_indices, today_suffix)
        return json.dumps(
            {
                "message": "Exact index was not found; wildcard candidates were found. Ask the user to confirm which index to use before mapping/search.",
                "requested_pattern": effective_pattern,
                "fallback_pattern": fallback_pattern,
                "matched_by": "wildcard_fallback",
                "needs_confirmation": True,
                "confirmation_question": "未找到精确索引，请向用户确认要使用下面哪个候选索引或视图。",
                "today": today_suffix,
                "search_pattern_hint": f"查询时请使用通配模式 {effective_pattern}-* 或 {effective_pattern}*，不要使用单个日期索引",
                "total": len(result),
                "indices": result,
            },
            ensure_ascii=False,
            indent=2,
        )
