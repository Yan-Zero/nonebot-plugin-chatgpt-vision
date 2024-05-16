""" 
This module is used to define the permission of the bot.
"""

from nonebot import get_plugin_config
from nonebot.adapters import Bot, Event
from nonebot.internal.permission import Permission
from nonebot.adapters.onebot.v11.event import GroupMessageEvent as V11G
from .config import Config

p_config: Config = get_plugin_config(Config)


class HumanLikeGroup(Permission):

    __slots__ = ()

    def __repr__(self) -> str:
        return "HumanLikeGroup()"

    async def __call__(self, bot: Bot, event: Event) -> bool:
        if not p_config.human_like_chat or not isinstance(event, V11G):
            return False

        try:
            group_id = str(event.group_id)
        except Exception:
            return False
        return group_id in HumanLikeGroup


HUMANLIKE_GROUP = Permission(HumanLikeGroup())
