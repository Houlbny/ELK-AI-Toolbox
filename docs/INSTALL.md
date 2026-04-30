# 安装指引：让大模型使用本项目（ELK MCP Server）

本项目支持两种传输模式：

| 模式 | 适用场景 | 部署方式 |
|------|---------|---------|
| **stdio**（默认） | 单人本地使用，客户端直接拉起进程 | 客户端配置 command + args |
| **SSE** | 服务端部署，多人/多客户端共用 | 服务端启动后，客户端配置 URL |

---

## 1. 前置条件

- Python 3.10+
- 已安装 `uv`（确保 `uvx` 可用）
- 可访问 ELK/Kibana 地址
- 有可用的 ELK 账号（建议最小权限）

快速检查：

```bash
uvx --version
```

## 2. 环境变量

无论哪种模式，都需要设置以下环境变量：

| 变量 | 必填 | 说明 |
|------|------|------|
| `ELK_HOST` | 是 | ES 或 Kibana 地址，如 `http://kibana:5601` |
| `ELK_USERNAME` | 是 | 账号 |
| `ELK_PASSWORD` | 是 | 密码 |

---

## 3. 模式一：stdio（本地模式）

客户端直接拉起 MCP 进程，通过 stdin/stdout 通信。适合 Claude Code、Cherry Studio 等本地客户端。

### 3.1 Claude Code

在项目根目录放置 `.mcp.json`：

```json
{
  "mcpServers": {
    "elk": {
      "command": "uvx",
      "args": [
        "--from",
        "/path/to/TTFund-ELK-Skill/mcp-server",
        "mcp-server-elk",
        "--mode", "kibana",
        "--timeout", "30s",
        "--max-results", "50",
        "--max-time-range", "7d",
        "--verify-certs", "true"
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

启动 Claude Code 并进入该项目目录，确认能看到 `elk` 服务与工具。

### 3.2 Cherry Studio

1. 打开 Cherry Studio 的 MCP Server 配置
2. 新增一个 `stdio` 类型服务（名称可为 `elk`）
3. 命令填 `uvx`，参数和环境变量同上
4. 保存后在会话里测试工具调用

### 3.3 其他 stdio 客户端

核心三要素：

- command: `uvx`
- args: `--from <repo>/mcp-server mcp-server-elk --mode kibana ...`
- env: `ELK_HOST` / `ELK_USERNAME` / `ELK_PASSWORD`

---

## 4. 模式二：SSE（服务端部署）

MCP 服务部署在服务端，客户端通过 HTTP SSE 连接。适合团队共用、远程访问场景。

### 4.1 架构

```
┌─────────────────┐         HTTP/SSE          ┌──────────────────────┐
│  客户端（本地）    │  ───────────────────────►  │  MCP Server（服务端）  │
│  - Claude Code   │   url: host:8000/sse      │  - 连接 ES/Kibana     │
│  - Cherry Studio │                           │  - 执行查询           │
│  - Skills 本地   │                           │                      │
└─────────────────┘                            └──────────────────────┘
```

**Skills 文件始终放在客户端本地**（如 Claude Code 的 `.claude/skills/` 目录），它们是给 AI 的提示词，不需要部署到服务端。本仓库以 `skills/` 作为源文件目录，`.claude/` 属于本地生成/安装目录，不提交到 Git。

### 4.2 服务端启动

在能访问 ES/Kibana 的服务器上执行：

```bash
# 先设置环境变量
export ELK_HOST="http://your-elk-host:5601"
export ELK_USERNAME="your_user"
export ELK_PASSWORD="your_password"

# 启动 SSE 服务
uvx --from /path/to/TTFund-ELK-Skill/mcp-server \
  mcp-server-elk \
  --mode kibana \
  --transport sse \
  --host 0.0.0.0 \
  --port 8000 \
  --timeout 30s \
  --max-results 50 \
  --max-time-range 7d \
  --verify-certs true
```

参数说明：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--transport` | `stdio` | 传输模式，`stdio` 或 `sse` |
| `--host` | `0.0.0.0` | SSE 绑定地址 |
| `--port` | `8000` | SSE 监听端口 |

启动后服务在 `http://<服务器IP>:8000/sse` 提供 SSE 端点。

### 4.3 客户端配置

客户端的 `.mcp.json` 只需配置 URL，无需 command 和 env：

```json
{
  "mcpServers": {
    "elk": {
      "type": "sse",
      "url": "http://your-server-ip:8000/sse"
    }
  }
}
```

Cherry Studio 同理：新增一个 `SSE` 类型服务，URL 填 `http://your-server-ip:8000/sse`。

### 4.4 后台运行（生产建议）

用 systemd、nohup 或 Docker 保持服务常驻：

```bash
# nohup 方式
nohup uvx --from /path/to/mcp-server \
  mcp-server-elk --mode kibana --transport sse --port 8000 \
  > /var/log/mcp-elk.log 2>&1 &

# 或用 Docker（需自行构建镜像）
```

---

## 5. 启动参数一览

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--mode` | `elasticsearch` | 后端模式：`elasticsearch` 直连 / `kibana` 走代理 |
| `--transport` | `stdio` | 传输协议：`stdio` / `sse` |
| `--host` | `0.0.0.0` | SSE 绑定地址（仅 SSE 模式） |
| `--port` | `8000` | SSE 监听端口（仅 SSE 模式） |
| `--timeout` | `30s` | ES 查询超时 |
| `--max-results` | `50` | 单次搜索最大返回条数 |
| `--max-time-range` | `7d` | 最大查询时间跨度 |
| `--max-buckets` | `20` | 聚合 buckets 上限 |
| `--verify-certs` | `true` | 是否验证 SSL 证书 |
| `--kibana-space` | 空 | Kibana Space ID |
| `--timezone-offset` | `8` | UTC 偏移小时数 |

## 6. 首次验证

无论哪种模式，建议按以下顺序验证：

1. `es_indices` — 确认连接正常
2. `es_mapping` — 确认字段可见
3. `es_search` — 用一个小时间范围做查询
4. `es_aggregate` — 做一次按 status 的聚合

## 7. 常见问题

### Q: 工具能列出索引，但搜索返回 0
- 时间字段是否正确（通常 `@timestamp`）
- 时间范围是否覆盖实际数据时间
- 查询条件是否过窄

### Q: 连接失败或超时
- `ELK_HOST` 是否可达
- 账号密码是否正确
- 是否需要调整 `--timeout`
- `--verify-certs` 是否与证书环境匹配

### Q: 客户端看不到工具
- stdio 模式：检查 `.mcp.json` 路径和 `uvx` 是否可执行
- SSE 模式：检查 URL 是否可达，服务是否已启动

### Q: SSE 模式连接被拒
- 检查服务端防火墙是否放行端口
- 确认 `--host 0.0.0.0` 而非 `127.0.0.1`
- 用 `curl http://server-ip:8000/sse` 测试连通性

## 8. 安全建议

- 不要把真实凭据写入 Git 历史
- 建议使用只读账号
- 按需收紧 `--max-results` 与 `--max-time-range`
- SSE 模式建议在内网或 VPN 环境使用，避免公网暴露
