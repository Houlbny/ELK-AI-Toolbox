# ELK AI Toolbox

ELK AI Toolbox 将 Elasticsearch / Kibana 查询能力封装为 MCP Server，使 Claude Code、Cherry Studio 以及其他支持 MCP 的 AI 客户端可以通过受控工具访问日志与指标数据。

## 项目特性

- 支持 `stdio` 与 `sse` 两种 MCP 传输模式，兼顾本地使用和团队共享部署。
- 支持 Elasticsearch 直连与 Kibana 代理模式。
- 内置查询超时、结果数量、时间范围、聚合桶数量和证书校验等安全边界。
- 提供索引发现、字段映射、检索、计数、聚合、字段枚举和服务端时间等常用工具。
- 配套 AI 使用指引，帮助模型先确认索引、字段和时间窗口，再执行精确查询。

## 快速开始

1. 安装基础环境：
   - Python 3.10+
   - `uv`，用于通过 `uvx` 启动 MCP Server
2. 复制 `.mcp.json.example` 为本地 `.mcp.json`。
3. 按实际环境填写 `ELK_HOST`、`ELK_USERNAME` 和 `ELK_PASSWORD`。
4. 在 MCP 客户端中加载配置，并调用 `es_indices` 验证连接。

完整安装步骤、多客户端接入和 SSE 部署说明见 [docs/INSTALL.md](docs/INSTALL.md)。

## MCP 配置示例

将 `<repo>/mcp-server` 替换为本仓库中 `mcp-server` 目录的实际路径。

```json
{
  "mcpServers": {
    "elk": {
      "command": "uvx",
      "args": [
        "--from",
        "<repo>/mcp-server",
        "mcp-server-elk",
        "--mode",
        "kibana",
        "--timeout",
        "30s",
        "--max-results",
        "50",
        "--max-time-range",
        "7d",
        "--verify-certs",
        "true"
      ],
      "env": {
        "ELK_HOST": "http://your-elk-host:5601",
        "ELK_USERNAME": "your_user",
        "ELK_PASSWORD": "your_password"
      }
    }
  }
}
```

> `.mcp.json` 应仅保存在本地环境中，不要将真实地址、账号或密码提交到仓库。

## 可用工具

| 工具 | 说明 |
|------|------|
| `es_indices` | 查看可用索引或数据视图 |
| `es_mapping` | 查看索引字段结构 |
| `es_count` | 统计匹配条件的文档数量 |
| `es_search` | 按索引、时间范围和查询条件检索文档 |
| `es_aggregate` | 按字段、时间范围和查询条件执行聚合 |
| `es_field_values` | 获取字段的候选枚举值 |
| `es_server_time` | 获取 MCP 服务端时间，用于计算今天、昨天、发布窗口等绝对时间范围 |

## 推荐查询流程

1. 先确认索引或数据视图范围。业务查询缺少索引、通配模式或系统名称时，应先通过 `es_indices` 收敛范围。
2. 查询前使用 `es_mapping` 查看字段结构，避免模型猜字段名或字段类型。
3. 最近 N 分钟的查询优先使用相对时间；今天、昨天、发布窗口等场景再通过 `es_server_time` 计算绝对时间。
4. 查询结果为空时，固定原索引和原时间范围，先用 `es_count` 建立基线，再逐项隔离查询条件。
5. 输出结论时保留完整时间范围、时区、索引名称和关键过滤条件，便于复核。

## 本地验证

```bash
uvx --from <repo>/mcp-server mcp-server-elk --help
```

## 安全建议

- 使用最小权限账号访问 Elasticsearch 或 Kibana。
- 不要提交 `.mcp.json`、`.env`、真实服务地址、账号或密码。
- 生产环境建议启用证书校验，并限制 SSE 服务的网络访问范围。
- 为高成本查询设置合理的 `--timeout`、`--max-results`、`--max-time-range` 和 `--max-buckets`。
