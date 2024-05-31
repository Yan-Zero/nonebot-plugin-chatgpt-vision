import tempfile
import aiofiles
from io import BytesIO
from PIL import Image
from typing import Optional
from nonebot import get_driver, on_command
from nonebot.adapters.onebot.v11 import (
    Message,
    MessageEvent,
    PrivateMessageEvent,
    GroupMessageEvent,
)
from nonebot.adapters.onebot.v11.message import MessageSegment as V11Seg
from nonebot.adapters.onebot.v11.helpers import ImageURLs
from nonebot.params import CommandArg
from nonebot.rule import to_me
from enum import Enum
import asyncio
from nonebot.permission import SUPERUSER
from openai import RateLimitError
from openai import BadRequestError

import aiohttp

from .chat import POOL


class Size(Enum):
    SMALL = "256x256"
    MEDIUM = "512x512"
    LARGE = "1024x1024"


# 全局变量，用于存储DALL·E的开关状态、图片尺寸，以及正在绘图的用户
drawing_users = {}  # 用于存储正在绘图的用户
DALLESwitchState = True  # 开关状态,默认关闭

drawing_users_lock = asyncio.Lock()  # 用于绘图用户的锁
DALLESwitchState_lock = asyncio.Lock()  # 用于保护DALLESwitchState

dall_drawing = on_command(
    "开关绘图",
    aliases={"开启绘图", "关闭绘图"},
    permission=SUPERUSER,
    priority=2,
    block=True,
)

superusers = get_driver().config.superusers


@dall_drawing.handle()
async def _(event: MessageEvent):
    global DALLESwitchState  # 在函数内部声明全局变量
    if isinstance(event, PrivateMessageEvent) and str(event.user_id) not in superusers:
        await dall_drawing.finish("私聊无法使用此功能")
    if isinstance(event, GroupMessageEvent):
        async with DALLESwitchState_lock:
            if not DALLESwitchState:
                DALLESwitchState = True
                await dall_drawing.finish("已开启绘图功能")
            else:
                DALLESwitchState = False
                await dall_drawing.finish("已关闭绘图功能")


dell_size = on_command(
    "绘图尺寸",
    rule=to_me(),
    aliases={"尺寸"},
    permission=SUPERUSER,
    priority=2,
    block=True,
)


async def draw_image(model: str, prompt: str, size=Size.LARGE.value, times: int = 3):
    for _ in range(times - 1):
        cilent = POOL(model=model)
        try:
            return await cilent.images.generate(model=model, prompt=prompt, size=size)
        except RateLimitError:
            POOL.RequestLimit(model=model, cilent=cilent, timeout=120)
    return await POOL(model=model).images.generate(
        model=model, prompt=prompt, size=size
    )


dall_drawing = on_command("画", rule=to_me(), aliases={"draw"}, priority=2, block=True)


@dall_drawing.handle()
async def _(event: MessageEvent, arg: Message = CommandArg()):
    await do_drawing(event, arg)


async def do_drawing(
    event: MessageEvent, arg: Optional[Message] = None, urls: Optional[ImageURLs] = None
):
    user_id = str(event.user_id)
    async with drawing_users_lock:
        if isinstance(event, PrivateMessageEvent) and user_id not in superusers:
            await dall_drawing.finish("私聊无法使用此功能")

        # 检查是否用户已经在绘图
        if user_id in drawing_users:
            await dall_drawing.finish(
                "你已经有一个绘图任务在进行中，请等待完成后再发起新的请求",
                at_sender=True,
            )

        if not DALLESwitchState:
            await dall_drawing.finish("绘图功能未开启")

        # 把用户添加到绘图用户列表
        drawing_users[user_id] = True

    success = False
    error = ""
    try:
        if urls is None and (arg is None or not arg):
            await dall_drawing.finish("请输入要绘制的内容")

        if urls is not None and (urls is None or len(urls) != 1):
            await dall_drawing.finish("您没有给出图片，或者您给出了多张图片")

        await dall_drawing.send("正在绘图，请稍等...", at_sender=True)

        # # 调用DALL·E绘图
        # if urls is not None:
        #     result = await img_img(await get_img(urls[0]))
        #     result = result.data[0].url
        # else:
        #     # 过滤敏感词
        #     prompt = gfw.filter(arg.extract_plain_text())
        #     result, success = await dalle.get_image(prompt, DALLEImageSize.value)
        result = await draw_image(model="dall-e-3", prompt=arg.extract_plain_text())
        result = result.data[0].url
        success = True
    except BadRequestError as bd:
        error = str(bd.message)
    except Exception as ex:
        error = str(ex)
    finally:
        # 无论成功或失败，都从绘图用户列表中删除
        async with drawing_users_lock:
            del drawing_users[user_id]
    response_message = V11Seg.image(result) if success else error
    await dall_drawing.finish(response_message, at_sender=True)
