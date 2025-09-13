import json

from typing import Dict, Any, List
from abc import ABC, abstractmethod

from .mcp import MCPSSEClient, MCPStdIOClient


class Tool(ABC):
    @abstractmethod
    def get_schema(self) -> Dict[str, Any]:
        """返回工具的 JSON Schema"""
        pass

    @abstractmethod
    async def execute(self, **kwargs) -> str:
        """执行工具"""
        pass


class BlockTool(Tool):
    def __init__(self, group_record):
        self.group_record = group_record

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "block_user",
                "description": "屏蔽用户",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "user_id": {"type": "string", "description": "要屏蔽的用户ID"},
                        "duration": {"type": "number", "description": "屏蔽时长（秒）"},
                    },
                    "required": ["user_id", "duration"],
                },
            },
        }

    async def execute(self, user_id: str, duration: float) -> str:
        self.group_record.block(user_id, duration)
        return f"已屏蔽用户 {user_id} {duration} 秒"


class ToolManager:
    def __init__(self):
        self.tools: Dict[str, Tool] = {}

    def register_tool(self, name: str, tool: Tool):
        self.tools[name] = tool

    def register_tools(self, mapping: Dict[str, Tool]):
        self.tools.update(mapping)

    def get_tools_schema(self) -> List[Dict[str, Any]]:
        return [tool.get_schema() for tool in self.tools.values()]

    async def execute_tool(self, name: str, **kwargs) -> str:
        if name not in self.tools:
            return f"工具 {name} 不存在"
        return await self.tools[name].execute(**kwargs)


class MCPTool(Tool):
    def __init__(
        self,
        mcp_client: MCPSSEClient | MCPStdIOClient,
        tool_name: str,
        tool_schema: Dict[str, Any],
    ):
        self.mcp_client = mcp_client
        self.tool_name = tool_name
        self.tool_schema = tool_schema

    def get_schema(self) -> Dict[str, Any]:
        return {"type": "function", "function": self.tool_schema}

    @staticmethod
    def _stringify_mcp_result(result: Any) -> str:
        # mcp[cli] 返回的 call_tool 结果通常带有 content 列表
        try:
            # 1) 结果对象形式（如 dataclass，带 content 属性）
            content = getattr(result, "content", None)
            if content is not None:
                parts: List[str] = []
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
