import os
import json
import yaml
import asyncio

from abc import ABC, abstractmethod
from typing import Any
from pathlib import Path
from nonebot import logger
from fastmcp import Client as FastMCPClient
from fastmcp.client.transports import (
    StdioTransport,
    StreamableHttpTransport,
    SSETransport,
)


class Tool(ABC):
    @abstractmethod
    def get_schema(self) -> dict[str, Any]:
        """返回工具的 JSON Schema"""
        pass

    @abstractmethod
    async def execute(self, **kwargs) -> str:
        """执行工具"""
        pass

    def get_name(self) -> str:
        """返回工具名称"""
        schema = self.get_schema()
        if schema.get("type") == "function":
            function = schema.get("function", {})
            return function.get("name", "unknown_tool")
        return "unknown_tool"


class ToolManager:
    """管理多个工具的注册与调用"""

    tools: dict[str, Tool]
    """工具名称 -> 工具实例"""
    enable: dict[str, bool]
    """工具名称 -> 是否启用"""

    def __init__(self):
        self.tools = {}
        self.enable = {}

    def register_tool(
        self, tool: Tool, name: str | None = None, default: bool = True
    ) -> str:
        if not name:
            name = tool.get_name()
        self.tools[name] = tool
        self.enable[name] = default
        return name

    def register_tools(self, mapping: dict[str, Tool]):
        self.tools.update(mapping)
        for name in mapping:
            self.enable[name] = True

    def enable_tool(self, name: str):
        if name in self.tools:
            self.enable[name] = True
        else:
            logger.warning(f"Tool {name} not found to enable")

    def disable_tool(self, name: str):
        if name in self.tools:
            self.enable[name] = False
        else:
            logger.warning(f"Tool {name} not found to disable")

    def get_tools_schema(self) -> list[dict[str, Any]]:
        return [
            tool.get_schema()
            for name, tool in self.tools.items()
            if self.enable.get(name, False)
        ]

    async def execute_tool(self, name: str, **kwargs) -> str:
        if not self.enable.get(name, False):
            logger.warning(f"Tool {name} is disabled")
            return f"工具 {name} 未启用"
        logger.info(f"Executing tool: {name} with args: {kwargs}")
        if name not in self.tools:
            logger.warning(f"Tool {name} not found")
            return f"工具 {name} 不存在"
        return await self.tools[name].execute(**kwargs)


class MCPUnifiedClient:
    """
    基于 FastMCP 的统一客户端封装，支持 stdio / SSE / HTTP（由 FastMCP 客户端自动处理）。
    spec 可以是：
      - 传输实例（StdioTransport / StreamableHttpTransport / SSETransport）
      - URL 字符串（http/https）（FastMCP 也支持）
      - 完整 MCP 配置（包含 mcpServers）
    """

    def __init__(self, spec: Any, start_timeout: float = 20.0):
        self.spec = spec
        self.start_timeout = start_timeout

    async def list_tools(self) -> list[dict[str, Any]]:
        try:
            async with asyncio.timeout(self.start_timeout):
                async with FastMCPClient(self.spec) as client:  # type: ignore[arg-type]
                    tools = await client.list_tools()
                    unified: list[dict[str, Any]] = []
                    for t in tools:
                        name = getattr(t, "name", None) or (
                            t.get("name") if isinstance(t, dict) else None
                        )
                        if not name:
                            continue
                        description = (
                            getattr(t, "description", None)
                            or (t.get("description") if isinstance(t, dict) else None)
                            or ""
                        )
                        input_schema = (
                            getattr(t, "input_schema", None)
                            or getattr(t, "inputSchema", None)
                            or (t.get("input_schema") if isinstance(t, dict) else None)
                            or (t.get("inputSchema") if isinstance(t, dict) else None)
                            or {}
                        )
                        unified.append(
                            {
                                "name": name,
                                "schema": {
                                    "name": name,
                                    "description": description,
                                    "parameters": input_schema,
                                },
                            }
                        )
                    return unified
        except Exception:
            return []

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        try:
            async with asyncio.timeout(self.start_timeout):
                async with FastMCPClient(self.spec) as client:  # type: ignore[arg-type]
                    return await client.call_tool(name, arguments)
        except Exception as ex:
            return {"error": f"工具 {name} 调用失败", "exception": str(ex)}


def _split_cmd(cmd: str) -> list[str]:
    import shlex

    try:
        return shlex.split(cmd, posix=False)
    except Exception:
        return cmd.split()


def load_mcp_clients_from_yaml(
    path: str | os.PathLike | None,
) -> list[MCPUnifiedClient]:
    """
    从 YAML 文件构建多个 MCP 客户端（统一封装版）。支持：
    - stdio: ["uvx my-mcp", "python -m server"] -> 使用 StdioTransport
    - sse: 列表，元素包含 url 与可选 headers -> 使用 SSETransport（兼容/旧）
    - http: 列表，元素包含 base_url/url、可选 headers -> 使用 StreamableHttpTransport

    也可在外部直接传入完整 MCP 配置或 URL，本函数仅针对该 YAML 形态进行解析。
    """
    if not path:
        return []
    p = Path(path)
    if not p.exists():
        return []
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return []

    multi: list[MCPUnifiedClient] = []

    # stdio
    stdio_cfg = data.get("stdio") or []
    if isinstance(stdio_cfg, dict):
        commands: list[str] = stdio_cfg.get("commands") or []
    elif isinstance(stdio_cfg, list):
        commands: list[str] = stdio_cfg

    if isinstance(commands, str):
        commands = [commands]
    for cmd in commands:
        if not isinstance(cmd, str) or not cmd.strip():
            continue
        parts = _split_cmd(cmd)
        if not parts:
            continue
        exe, args = parts[0], parts[1:]
        transport = StdioTransport(command=exe, args=args)
        multi.append(MCPUnifiedClient(transport))

    # sse endpoints（Legacy）
    sse_cfg = data.get("sse") or []
    if isinstance(sse_cfg, dict):
        sse_cfg = [sse_cfg]
    for ep in sse_cfg:
        if not isinstance(ep, dict):
            continue
        url = ep.get("url") or ep.get("sse_url")
        if not url:
            continue
        headers = ep.get("headers") or None
        transport = SSETransport(url=url, headers=headers or None)
        multi.append(MCPUnifiedClient(transport))

    # http endpoints -> Streamable HTTP（推荐）
    http_cfg = data.get("http") or []
    if isinstance(http_cfg, dict):
        http_cfg = [http_cfg]
    for ep in http_cfg:
        if not isinstance(ep, dict):
            continue
        base_url = ep.get("base_url") or ep.get("url")
        if not base_url:
            continue
        headers = ep.get("headers") or {}
        ahn = ep.get("auth_header_name")
        ahv = ep.get("auth_header_value")
        if ahn and ahv:
            headers = dict(headers or {})
            headers[str(ahn)] = str(ahv)
        transport = StreamableHttpTransport(url=base_url, headers=headers or None)
        multi.append(MCPUnifiedClient(transport))

    return multi


class MCPTool(Tool):
    def __init__(
        self,
        mcp_client: MCPUnifiedClient,
        tool_name: str,
        tool_schema: dict[str, Any],
    ):
        self.mcp_client = mcp_client
        self.tool_name = tool_name
        self.tool_schema = tool_schema

    def get_schema(self) -> dict[str, Any]:
        return {"type": "function", "function": self.tool_schema}

    @staticmethod
    def _stringify_mcp_result(result: Any) -> str:
        # mcp[cli] 返回的 call_tool 结果通常带有 content 列表
        try:
            # 0) dict 形式且包含 content
            if isinstance(result, dict) and "content" in result:
                parts: list[str] = []
                content = result.get("content")
                if isinstance(content, list):
                    for p in content:
                        text = None
                        if isinstance(p, dict):
                            text = p.get("text")
                        if text is not None:
                            parts.append(str(text))
                        else:
                            parts.append(json.dumps(p, ensure_ascii=False, default=str))
                return "\n".join(parts).strip() or json.dumps(
                    result, ensure_ascii=False, default=str
                )

            # 1) 结果对象形式（如 dataclass，带 content 属性）
            content = getattr(result, "content", None)
            if content is not None:
                parts: list[str] = []
                for p in content:
                    # p 可能是对象或 dict
                    text = getattr(p, "text", None)
                    if text is None and isinstance(p, dict):
                        text = p.get("text")
                    if text is not None:
                        parts.append(str(text))
                    else:
                        parts.append(json.dumps(p, ensure_ascii=False, default=str))
                return "\n".join(parts).strip() or str(result)

            # 2) dict/list 等可序列化结构
            if isinstance(result, (dict, list)):
                return json.dumps(result, ensure_ascii=False, default=str)

            # 3) 兜底
            return str(result)
        except Exception:
            return str(result)

    async def execute(self, **kwargs) -> str:
        # 调用 MCP 服务器
        result = await self.mcp_client.call_tool(self.tool_name, kwargs)
        return self._stringify_mcp_result(result)
