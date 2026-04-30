import json
from datetime import datetime, timezone, timedelta


def register(mcp, config):
    tz_offset = int(getattr(config, "timezone_offset_hours", getattr(config, "timezone_offset", 8)))
    tz = timezone(timedelta(hours=tz_offset))
    tz_label = f"UTC{tz_offset:+d}"

    @mcp.tool()
    def es_server_time() -> str:
        """返回 MCP 服务器的本地当前时间。

        最近/过去 N 分钟这类窗口应优先在查询工具中传 relative_minutes，
        不需要调用本工具。只有需要把「今天」「昨天」「刚发布」
        或发布前后窗口换算为绝对 start_time / end_time 时，才调用本工具获取当前时间。
        不要向用户询问当前时间，也不要回答“不知道当前时间”。

        示例：
        - 用户说「过去半小时」：直接给查询工具传 relative_minutes=30
        - 用户说「今天」：调用本工具后计算 start_time = date + "T00:00:00"，end_time = current_time

        Returns:
            当前时间（ISO 格式）和时区信息。
        """
        now = datetime.now(tz)
        return json.dumps({
            "current_time": now.isoformat(),
            "current_time_display": f"{now.strftime('%Y-%m-%d %H:%M:%S')} {tz_label}",
            "timezone": tz_label,
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H:%M:%S"),
        }, ensure_ascii=False)
