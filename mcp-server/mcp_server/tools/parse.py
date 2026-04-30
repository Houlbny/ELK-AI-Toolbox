"""JSON 参数解析工具。

LLM 调用 MCP 工具时，参数可能是 dict（已解析）、合法 JSON 字符串、
或带有常见错误的 JSON 字符串。此模块统一处理并尽力修复。
"""

import json
import re
from json import JSONDecodeError
from typing import Any, Union


def _fix_json(text: str) -> str:
    """尝试修复 LLM 常见的 JSON 格式错误。"""
    s = text.strip()

    # 双重转义: {\"key\": \"value\"} -> {"key": "value"}
    if s.startswith('{') and '\\"' in s and '"' not in s.replace('\\"', ''):
        s = s.replace('\\"', '"')

    # 单引号替换为双引号: {'key': 'value'} -> {"key": "value"}
    if "'" in s and '"' not in s:
        s = s.replace("'", '"')

    # 去掉尾部逗号: {"a": 1,} -> {"a": 1}
    s = re.sub(r',\s*([}\]])', r'\1', s)

    # 补齐未闭合的括号
    opens = 0
    closes = 0
    in_string = False
    escape = False
    for ch in s:
        if escape:
            escape = False
            continue
        if ch == '\\':
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == '{':
            opens += 1
        elif ch == '}':
            closes += 1
    if opens > closes:
        s += '}' * (opens - closes)

    return s


def parse_json_like(value: Any, field: str) -> Union[dict, list]:
    """接受 dict/list 或 JSON 字符串，统一返回解析后的对象。

    解析顺序：
    1. 已经是 dict/list -> 直接返回
    2. 合法 JSON 字符串 -> json.loads
    3. 尝试修复常见错误后再 json.loads
    4. 全部失败 -> 抛出 ValueError
    """
    if isinstance(value, (dict, list)):
        return value

    if not isinstance(value, str):
        raise ValueError(f"Invalid type for {field}: expected object or string, got {type(value).__name__}")

    # 第一次：直接解析
    try:
        parsed = json.loads(value)
        if isinstance(parsed, (dict, list)):
            return parsed
        raise ValueError(f"Invalid JSON for {field}: expected object or array, got {type(parsed).__name__}")
    except JSONDecodeError:
        pass

    # 第二次：尝试修复后解析
    fixed = _fix_json(value)
    try:
        parsed = json.loads(fixed)
        if isinstance(parsed, (dict, list)):
            return parsed
        raise ValueError(f"Invalid JSON for {field}: expected object or array, got {type(parsed).__name__}")
    except JSONDecodeError as error:
        raise ValueError(f"Invalid JSON for {field}: {error}") from error
