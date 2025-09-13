import shlex
import asyncio
import yaml
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from mcp.client.session import ClientSession
from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client


class MCPStdIOClient:
    """
    使用 mcp[cli] 的 stdio 客户端与单个 MCP 服务器交互（一次性会话）。
    - command: 一条命令字符串，例如 "uvx my-mcp-server" 或 "python -m my_server"。
    """

    def __init__(self, command: Optional[str] = None, start_timeout: float = 20.0):
        self.command: Optional[str] = command
        self.start_timeout = start_timeout

    @staticmethod
    def _split_cmd(cmd: str) -> List[str]:
        try:
            return shlex.split(cmd, posix=False)
        except Exception:
            return cmd.split()

    async def list_tools(self) -> List[Dict[str, Any]]:
        if not self.command:
            return []
        try:
            async with asyncio.timeout(self.start_timeout):
                args = self._split_cmd(self.command)
                async with stdio_client(*args) as (read, write):  # type: ignore
                    async with ClientSession(read, write) as session:  # type: ignore
                        await session.initialize()
                        tools = (await session.list_tools()).tools
                        unified: List[Dict[str, Any]] = []
                        for t in tools:
                            unified.append(
                                {
                                    "name": t.name,
                                    "schema": {
                                        "name": t.name,
                                        "description": t.description or "",
                                        "parameters": t.inputSchema,
                                    },
                                }
                            )
                        return unified
        except Exception:
            return []

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        if not self.command:
            return {"error": f"工具 {name} 调用失败"}
        try:
            async with asyncio.timeout(self.start_timeout):
                args = self._split_cmd(self.command)
                async with stdio_client(*args) as (read, write):  # type: ignore
                    async with ClientSession(read, write) as session:  # type: ignore
                        await session.initialize()
                        return await session.call_tool(name, arguments)
        except Exception:
            return {"error": f"工具 {name} 调用失败"}


class MCPSSEClient:
    """
    使用 mcp[cli] 的 SSE 客户端连接单个 MCP 端点（一次性会话）。
    - url: SSE URL
    - headers: 可选请求头
    """

    def __init__(
        self,
        url: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        start_timeout: float = 20.0,
    ):
        self.url = url
        self.headers = headers
        self.start_timeout = start_timeout

    async def list_tools(self) -> List[Dict[str, Any]]:
        if not self.url:
            return []
        try:
            async with asyncio.timeout(self.start_timeout):
                async with sse_client(self.url, headers=self.headers) as (read, write):  # type: ignore
                    async with ClientSession(read, write) as session:  # type: ignore
                        await session.initialize()
                        tools = (await session.list_tools()).tools
                        unified: List[Dict[str, Any]] = []
                        for t in tools:
                            unified.append(
                                {
                                    "name": t.name,
                                    "schema": {
                                        "name": t.name,
                                        "description": t.description or "",
                                        "parameters": t.inputSchema,
                                    },
                                }
                            )
                        return unified
        except Exception:
            return []

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        if not self.url:
            return {"error": f"工具 {name} 调用失败"}
        try:
            async with asyncio.timeout(self.start_timeout):
                async with sse_client(self.url, headers=self.headers) as (read, write):  # type: ignore
                    async with ClientSession(read, write) as session:  # type: ignore
                        await session.initialize()
                        return await session.call_tool(name, arguments)
        except Exception as e:
            return {"error": f"工具 {name} 调用失败"}


class MultiMCPClient:
    """聚合多个 mcp[cli] 客户端（stdio/SSE），统一 list_tools/call_tool 接口。"""

    def __init__(self, clients: Optional[List[MCPSSEClient | MCPStdIOClient]] = None):
        self.clients = clients or []

    def extend(self, client: MCPSSEClient | MCPStdIOClient | None):
        if not client:
            return
        if isinstance(client, MultiMCPClient):
            self.clients.extend(client.clients)
        else:
            self.clients.append(client)

    async def list_tools(self) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for c in self.clients:
            try:
                tools = await c.list_tools()
                results.extend(tools or [])
            except Exception:
                continue
        seen: set[str] = set()
        deduped: List[Dict[str, Any]] = []
        for t in results:
            name = t.get("name") if isinstance(t, dict) else None
            if not name or name in seen:
                continue
            seen.add(name)
            deduped.append(t)
        return deduped

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        last_error: Any = None
        for c in self.clients:
            try:
                return await c.call_tool(name, arguments)
            except Exception as e:
                last_error = str(e)
                continue
        return {"error": last_error or f"工具 {name} 调用失败"}


def load_mcp_clients_from_yaml(
    path: str | os.PathLike | None,
) -> Optional[MultiMCPClient]:
    """
    从 YAML 文件构建多个 MCP 客户端，支持：
    - stdio.commands: ["uvx my-mcp", "python -m server"]
    - sse: 列表，元素包含 url 与可选 headers

    返回 MultiMCPClient 或 None（文件不存在或为空）。
    """
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        return None
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return None

    multi = MultiMCPClient([])

    # stdio commands -> 一个命令一个客户端
    stdio_cfg = data.get("stdio") or {}
    commands: List[str] = []
    if isinstance(stdio_cfg, dict):
        commands = stdio_cfg.get("commands") or []
    if isinstance(commands, str):
        commands = [commands]
    if commands:
        for cmd in commands:
            if isinstance(cmd, str) and cmd.strip():
                multi.extend(MCPStdIOClient(command=cmd))

    # sse endpoints -> 一个端点一个客户端
    sse_cfg = data.get("sse") or []
    if isinstance(sse_cfg, dict):
        sse_cfg = [sse_cfg]
    endpoints: List[Dict[str, Any]] = []
    for ep in sse_cfg:
        if not isinstance(ep, dict):
            continue
        url = ep.get("url") or ep.get("sse_url")
        if not url:
            continue
        headers = ep.get("headers") or None
        endpoints.append({"url": url, "headers": headers})
    if endpoints:
        for ep in endpoints:
            multi.extend(MCPSSEClient(url=ep["url"], headers=ep.get("headers")))

    if not multi.clients:
        return None
    return multi
