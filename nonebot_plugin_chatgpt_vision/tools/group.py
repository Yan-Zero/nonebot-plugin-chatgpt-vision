from typing import Any
from . import Tool


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
