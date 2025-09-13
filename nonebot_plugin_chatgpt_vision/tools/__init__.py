import json

from typing import Dict, Any, List
from abc import ABC, abstractmethod


class Tool(ABC):
    @abstractmethod
    def get_schema(self) -> Dict[str, Any]:
        """返回工具的 JSON Schema"""
        pass

    @abstractmethod
    async def execute(self, **kwargs) -> str:
        """执行工具"""
        pass


class SearchTool(Tool):
    def __init__(self, searcher):
        self.searcher = searcher

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "search",
                "description": "搜索网络信息",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "搜索查询内容"}
                    },
                    "required": ["query"],
                },
            },
        }

    async def execute(self, query: str) -> str:
        if not self.searcher:
            return "搜索功能不可用"
        return await self.searcher.search(query)


class ClickTool(Tool):
    def __init__(self, searcher):
        self.searcher = searcher

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "click_result",
                "description": "查看搜索结果的详细内容",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "index": {"type": "integer", "description": "要查看的结果索引"}
                    },
                    "required": ["index"],
                },
            },
        }

    async def execute(self, index: int) -> str:
        if not self.searcher:
            return "搜索功能不可用"
        return await self.searcher.mclick(index)


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
    def __init__(self, mcp_client, tool_name: str, tool_schema: Dict[str, Any]):
        self.mcp_client = mcp_client
        self.tool_name = tool_name
        self.tool_schema = tool_schema

    def get_schema(self) -> Dict[str, Any]:
        return {"type": "function", "function": self.tool_schema}

    async def execute(self, **kwargs) -> str:
        # 调用 MCP 服务器
        result = await self.mcp_client.call_tool(self.tool_name, kwargs)
        return json.dumps(result, ensure_ascii=False)


class MCPAdapter:
    def __init__(self, mcp_client):
        self.mcp_client = mcp_client

    async def get_tools(self) -> List[MCPTool]:
        """从 MCP 服务器获取可用工具"""
        tools_list = await self.mcp_client.list_tools()
        return [
            MCPTool(self.mcp_client, tool["name"], tool["schema"])
            for tool in tools_list
        ]
