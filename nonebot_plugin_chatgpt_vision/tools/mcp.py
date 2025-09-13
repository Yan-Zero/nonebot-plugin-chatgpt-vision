import shlex
import aiohttp
import asyncio

from typing import Any, Dict, List, Optional
from nonebot import get_plugin_config
from mcp.client.session import ClientSession  # type: ignore
from mcp.client.stdio import stdio_client  # type: ignore

from ..config import Config


class HttpMCPClient:
    def __init__(
        self,
        base_url: str | None = None,
        tools_endpoint: str | None = None,
        call_endpoint: str | None = None,
        auth_header_name: str | None = None,
        auth_header_value: str | None = None,
    ):
        p_config: Config = get_plugin_config(Config)
        self.base_url = (base_url or p_config.mcp_server_url or "").rstrip("/")
        self.tools_endpoint = tools_endpoint or p_config.mcp_tools_endpoint
        self.call_endpoint = call_endpoint or p_config.mcp_call_endpoint
        self.auth_header_name = auth_header_name or p_config.mcp_auth_header_name
        self.auth_header_value = auth_header_value or p_config.mcp_auth_header_value

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.auth_header_name and self.auth_header_value:
            headers[self.auth_header_name] = self.auth_header_value
        return headers

    async def list_tools(self) -> List[Dict[str, Any]]:
        if not self.base_url:
            return []
        url = f"{self.base_url}{self.tools_endpoint}"
        async with aiohttp.ClientSession(headers=self._headers()) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json(content_type=None)
                tools = data.get("tools", data) if isinstance(data, dict) else data
                result: List[Dict[str, Any]] = []
                for t in tools or []:
                    # 兼容直接返回 OpenAI function schema 或自定义 schema
                    if (
                        isinstance(t, dict)
                        and "function" in t
                        and t.get("type") == "function"
                    ):
                        fn = t["function"]
                        if "name" in fn:
                            result.append({"name": fn["name"], "schema": fn})
                            continue
                    name = t.get("name") if isinstance(t, dict) else None
                    if not name:
                        continue
                    schema = {
                        "name": name,
                        "description": t.get("description", ""),
                        "parameters": t.get(
                            "parameters", {"type": "object", "properties": {}}
                        ),
                    }
                    result.append({"name": name, "schema": schema})
                return result

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        if not self.base_url:
            return {"error": "mcp base url not configured"}
        url = f"{self.base_url}{self.call_endpoint}"
        payload = {"name": name, "arguments": arguments}
        async with aiohttp.ClientSession(headers=self._headers()) as session:
            async with session.post(url, json=payload) as resp:
                try:
                    return await resp.json(content_type=None)
                except Exception:
                    return await resp.text()


class MCPStdIOClient:
    """
    通过 mcp[cli] 与一个或多个 MCP 服务器以 stdio 方式交互的轻量客户端。
    - commands: 每个元素是一条命令字符串，例如 "uvx my-mcp-server" 或 "python -m my_server"。
    设计为“短连接”：每次 list/call 都启动子进程并在完成后关闭，避免持久会话管理复杂性。
    """

    def __init__(
        self, commands: Optional[List[str]] = None, start_timeout: float = 20.0
    ):
        self.commands: List[str] = commands or []
        self.start_timeout = start_timeout

    @staticmethod
    def _split_cmd(cmd: str) -> List[str]:
        try:
            # Windows 下也使用 shlex.split，关闭 POSIX 规则可更好处理引号
            return shlex.split(cmd, posix=False)
        except Exception:
            return cmd.split()

    async def _with_session(self, cmd: str, coro) -> Any:
        """启动一次性会话并执行传入的协程函数。"""
        args = self._split_cmd(cmd)
        # 打开一次性连接
        async with stdio_client(*args) as (read, write):  # type: ignore
            async with ClientSession(read, write) as session:  # type: ignore
                # 不同版本 API 可能是 initialize/start，做兼容调用
                if hasattr(session, "initialize"):
                    await getattr(session, "initialize")()  # type: ignore
                elif hasattr(session, "start"):
                    await getattr(session, "start")()  # type: ignore
                return await coro(session)

    async def list_tools(self) -> List[Dict[str, Any]]:
        """
        返回统一结构 [{ name, schema }]，其中 schema 符合 OpenAI function schema。
        """
        results: List[Dict[str, Any]] = []
        for cmd in self.commands:
            try:

                async def _list(session):
                    # 兼容不同实现：list_tools/tools
                    list_fn = getattr(session, "list_tools", None)
                    if callable(list_fn):
                        resp = await list_fn()
                    else:
                        tools_attr = getattr(session, "tools", None)
                        resp = (
                            await tools_attr()
                            if callable(tools_attr)
                            else (tools_attr or [])
                        )

                    tools_list = []
                    # resp 可能是 dict/list/对象列表
                    if isinstance(resp, dict) and "tools" in resp:
                        tools_list = resp["tools"]
                    else:
                        tools_list = resp or []

                    unified: List[Dict[str, Any]] = []
                    for t in tools_list:
                        # 对象或字典取字段
                        name = getattr(t, "name", None) or (
                            t.get("name") if isinstance(t, dict) else None
                        )
                        if not name:
                            continue
                        description = getattr(t, "description", None) or (
                            t.get("description") if isinstance(t, dict) else ""
                        )
                        # 输入 schema 可能是 inputSchema / schema / parameters
                        parameters = (
                            getattr(t, "inputSchema", None)
                            or getattr(t, "schema", None)
                            or (t.get("inputSchema") if isinstance(t, dict) else None)
                            or (t.get("schema") if isinstance(t, dict) else None)
                            or (t.get("parameters") if isinstance(t, dict) else None)
                            or {"type": "object", "properties": {}}
                        )
                        unified.append(
                            {
                                "name": name,
                                "schema": {
                                    "name": name,
                                    "description": description or "",
                                    "parameters": parameters,
                                },
                            }
                        )
                    return unified

                unified = await asyncio.wait_for(
                    self._with_session(cmd, _list), timeout=self.start_timeout
                )
                results.extend(unified)
            except Exception:
                # 单个服务失败不影响整体
                continue
        # 去重（按 name）
        seen = set()
        deduped: List[Dict[str, Any]] = []
        for t in results:
            if t["name"] in seen:
                continue
            seen.add(t["name"])
            deduped.append(t)
        return deduped

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        # 逐个服务尝试调用，谁先成功用谁
        last_error: Any = None
        for cmd in self.commands:
            try:

                async def _call(session):
                    # 兼容不同实现：call_tool/callTool/invoke
                    for attr in ("call_tool", "callTool", "invoke_tool", "invokeTool"):
                        fn = getattr(session, attr, None)
                        if callable(fn):
                            return await fn(name, arguments)
                    # 一些实现可能通过请求对象
                    call = getattr(session, "call", None)
                    if callable(call):
                        return await call(
                            {"type": "tool", "name": name, "arguments": arguments}
                        )
                    raise RuntimeError("MCP 客户端不支持调用工具的 API")

                return await asyncio.wait_for(
                    self._with_session(cmd, _call), timeout=self.start_timeout
                )
            except Exception as e:
                last_error = str(e)
                continue
        return {"error": last_error or f"工具 {name} 调用失败"}
