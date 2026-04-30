---
name: elk-trace
description: 通过 traceId 查询请求调用链路。当用户提到 traceId、trace、链路追踪、调用链时触发。
---

# traceId 链路查询

根据 traceId 查询完整请求链路，按时间线展示各服务处理过程。全局索引、时间、字段和空结果规则以 MCP instructions 为准。

## 参数

- traceId：必须；未提供时先询问。
- 索引范围：可由服务名、数据视图或索引模式推断。只有 traceId 而无线索时，可先用 `es_indices(pattern="*")` 探索候选索引，再收窄查询范围。
- 时间范围：未指定时默认最近 1 小时，查询工具传 `relative_minutes=60`。

## 流程

1. 用 `es_indices` 确认索引范围；按天切分的日志查询使用通配模式。
2. 用 `es_mapping` 查找 traceId、时间、服务名、spanId、日志级别和消息字段。
3. 字段或 traceId 格式不确定时，在同一时间范围内用 `es_field_values` 或小样本 `es_search` 确认。
4. 调用 `es_search` 按 traceId 精确匹配，按时间字段升序，默认 size=50。
5. 结果为空时按全局规则做基线 count，并隔离 traceId 字段、服务名和时间字段。

## 输出

- 先说明查询时间跨度、命中数量和涉及服务。
- 按时间线展示：完整日期时间（含时区）｜服务｜级别｜消息摘要。
- 标出 ERROR/WARN、span 父子关系（如字段存在）和可能的失败点。
