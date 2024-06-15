import yaml
import pathlib
import base64
import aiohttp
from nonebot import get_driver, on_command
from nonebot.adapters.onebot.v11 import (
    MessageEvent,
    PrivateMessageEvent,
)
from nonebot.adapters.onebot.v11 import GroupMessageEvent as V11GME
from nonebot.adapters.onebot.v11.message import MessageSegment as V11Seg
from nonebot.params import CommandArg
from nonebot.rule import to_me
from nonebot.permission import SUPERUSER


superusers = get_driver().config.superusers
# read = on_command(
#     "read",
#     rule=to_me(),
#     priority=5,
#     force_whitespace=True,
#     block=True,
# )


async def send_image_as_base64(url: str):
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                b64_encoded = base64.b64encode(await response.read()).decode("utf-8")
                return f"data:image/jpeg;base64,{b64_encoded}"
            else:
                return None


# @read.handle()
# async def _(event: MessageEvent, args=CommandArg()):
#     if isinstance(event, PrivateMessageEvent) and str(event.user_id) not in superusers:
#         await read.finish("私聊无法使用此功能")
#     if isinstance(event, V11GME):
#         if not event.reply:
#             await read.finish("请先回复一条消息")
#         try:
#             rsp = await POOL("tts-1-hd").audio.speech.create(
#                 model="tts-1-hd",
#                 voice="onyx",
#                 input=event.reply.message.extract_plain_text(),
#             )
#             await read.send(V11Seg.record(await rsp.aread()))
#         except Exception as ex:
#             await read.finish(f"发生错误: {ex}")
