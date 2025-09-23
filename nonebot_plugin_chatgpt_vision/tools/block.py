from typing import Any
from . import Tool


class BlockTool(Tool):
    def __init__(self, group_record):
        self.group_record = group_record

    def get_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "block_user",
                "description": "屏蔽用户，这个功能是让你看不到用户的消息，但不会阻止用户发送消息。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "user_id": {"type": "string", "description": "要屏蔽的用户ID"},
                        "duration": {
                            "type": "number",
                            "description": "屏蔽时长（秒），如果为0则是取消屏蔽。正数的话，则是累加屏蔽时间。",
                        },
                    },
                    "required": ["user_id", "duration"],
                },
            },
        }

    async def execute(self, user_id: str, duration: float) -> str:
        duration = self.group_record.block(user_id, duration)
        if duration <= 0:
            return f"已取消屏蔽用户 {user_id}"
        return f"已屏蔽用户 {user_id} {duration:.2f} 秒"


class ListBlockedTool(Tool):
    def __init__(self, group_record):
        self.group_record = group_record

    def get_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "list_blocked_users",
                "description": "列出当前被屏蔽的用户",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        }

    async def execute(self, **kwargs) -> str:
        blocked = self.group_record.list_blocked()
        if not blocked:
            return "当前没有被屏蔽的用户"
        return "当前被屏蔽的用户有：\n" + "\n".join(
            f"{k}（剩余{v:.1f}秒）" for k, v in blocked
        )


class BanUser(Tool):
    def __init__(self, group_record):
        self.group_record = group_record

    def get_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "ban_user",
                "description": "Ban a user. 这个功能会阻止用户发送消息。并且你不需要告知用户已被封禁。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "user_id": {
                            "type": "string",
                            "description": "The ID of the user to be banned",
                        },
                        "duration": {
                            "type": "number",
                            "description": "Duration of the ban (in seconds). If 0, it means unban.",
                        },
                    },
                    "required": ["user_id", "duration"],
                },
            },
        }

    async def execute(self, user_id: str, duration: float) -> str:
        self.group_record.ban(user_id, duration)
        return f"User {user_id} has been banned for {duration} seconds"
