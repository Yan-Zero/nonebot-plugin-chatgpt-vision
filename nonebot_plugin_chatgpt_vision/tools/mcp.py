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
    使用 mcp[cli] 的 stdio 客户端与一个或多个 MCP 服务器交互（一次性会话）。
    - commands: 每个元素是一条命令字符串，例如 "uvx my-mcp-server" 或 "python -m my_server"。
    """

    def __init__(
        self, commands: Optional[List[str]] = None, start_timeout: float = 20.0
    ):
        self.commands: List[str] = commands or []
        self.start_timeout = start_timeout

    @staticmethod
    def _split_cmd(cmd: str) -> List[str]:
        try:
            return shlex.split(cmd, posix=False)
        except Exception:
            return cmd.split()

    async def _with_session(self, cmd: str, coro) -> Any:
        args = self._split_cmd(cmd)
        async with stdio_client(*args) as (read, write):  # type: ignore
            async with ClientSession(read, write) as session:  # type: ignore
                await session.initialize()
                return await coro(session)

    async def list_tools(self) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for cmd in self.commands:
            try:

                async def _list(session: ClientSession):
                    tools = await session.list_tools()
                    unified: List[Dict[str, Any]] = []
                    for t in tools:
                        name = t.name
                        desc = t.description or ""
                        params = getattr(
                            t, "inputSchema", {"type": "object", "properties": {}}
                        )
                        unified.append(
                            {
                                "name": name,
                                "schema": {
                                    "name": name,
                                    "description": desc,
                                    "parameters": params,
                                },
                            }
                        )
                    return unified

                unified = await asyncio.wait_for(
                    self._with_session(cmd, _list), timeout=self.start_timeout
                )
                results.extend(unified)
            except Exception:
                continue
        # 去重
        seen = set()
        deduped: List[Dict[str, Any]] = []
        for t in results:
            if t["name"] in seen:
                continue
            seen.add(t["name"])
            deduped.append(t)
        return deduped

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        last_error: Any = None
        for cmd in self.commands:
            try:

                async def _call(session: ClientSession):
                    return await session.call_tool(name, arguments)

                return await asyncio.wait_for(
                    self._with_session(cmd, _call), timeout=self.start_timeout
                )
            except Exception as e:
                last_error = str(e)
                continue
        return {"error": last_error or f"工具 {name} 调用失败"}


class MCPSSEClient:
    """
    使用 mcp[cli] 的 SSE 客户端连接一个或多个 MCP 端点（一次性会话）。
    - endpoints: [{ url: str, headers?: Dict[str, str] }]
    """

    def __init__(
        self,
        endpoints: Optional[List[Dict[str, Any]]] = None,
        start_timeout: float = 20.0,
    ):
        self.endpoints = endpoints or []
        self.start_timeout = start_timeout

    async def _with_session(
        self, url: str, headers: Optional[Dict[str, str]], coro
    ) -> Any:
        async with sse_client(url, headers=headers) as (read, write):  # type: ignore
            async with ClientSession(read, write) as session:  # type: ignore
                await session.initialize()
                return await coro(session)

    async def list_tools(self) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for ep in self.endpoints:
            try:
                url = ep.get("url")
                headers = ep.get("headers") or None
                if not url:
                    continue

                async def _list(session: ClientSession):
                    tools = await session.list_tools()
                    unified: List[Dict[str, Any]] = []
                    for t in tools:
                        name = t.name
                        desc = t.description or ""
                        params = getattr(
                            t, "inputSchema", {"type": "object", "properties": {}}
                        )
                        unified.append(
                            {
                                "name": name,
                                "schema": {
                                    "name": name,
                                    "description": desc,
                                    "parameters": params,
                                },
                            }
                        )
                    return unified

                unified = await asyncio.wait_for(
                    self._with_session(url, headers, _list), timeout=self.start_timeout
                )
                results.extend(unified)
            except Exception:
                continue
        # 去重
        seen = set()
        deduped: List[Dict[str, Any]] = []
        for t in results:
            if t["name"] in seen:
                continue
            seen.add(t["name"])
            deduped.append(t)
        return deduped

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        last_error: Any = None
        for ep in self.endpoints:
            try:
                url = ep.get("url")
                headers = ep.get("headers") or None
                if not url:
                    continue

                async def _call(session: ClientSession):
                    return await session.call_tool(name, arguments)

                return await asyncio.wait_for(
                    self._with_session(url, headers, _call), timeout=self.start_timeout
                )
            except Exception as e:
                last_error = str(e)
                continue
        return {"error": last_error or f"工具 {name} 调用失败"}


class MultiMCPClient:
    """聚合多个 mcp[cli] 客户端（stdio/SSE），统一 list_tools/call_tool 接口。"""

    def __init__(self, clients: Optional[List[object]] = None):
        self.clients = clients or []

    def extend(self, client: object | None):
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

    # stdio commands
    stdio_cfg = data.get("stdio") or {}
    commands: List[str] = []
    if isinstance(stdio_cfg, dict):
        commands = stdio_cfg.get("commands") or []
    if isinstance(commands, str):
        commands = [commands]
    if commands:
        multi.extend(MCPStdIOClient(commands=commands))

    # sse endpoints
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
        multi.extend(MCPSSEClient(endpoints=endpoints))

    if not multi.clients:
        return None
    return multi
