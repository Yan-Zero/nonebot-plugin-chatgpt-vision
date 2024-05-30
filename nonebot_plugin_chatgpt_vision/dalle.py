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
import aiohttp

from .chat import POOL


class Size(Enum):
    SMALL = "256x256"
    MEDIUM = "512x512"
    LARGE = "1024x1024"


size_mapping = {"小": Size.SMALL, "中": Size.MEDIUM, "大": Size.LARGE}

# 全局变量，用于存储DALL·E的开关状态、图片尺寸，以及正在绘图的用户
drawing_users = {}  # 用于存储正在绘图的用户
DALLESwitchState = True  # 开关状态,默认关闭
DALLEImageSize = Size.SMALL  # 图片尺寸，默认为256x256

DALLEImageSize_lock = asyncio.Lock()  # 用于保护DALLEImageSize
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


@dell_size.handle()
async def _(event: MessageEvent, arg: Message = CommandArg()):
    global DALLEImageSize  # 在函数内部声明全局变量
    if isinstance(event, PrivateMessageEvent) and str(event.user_id) not in superusers:
        await dall_drawing.finish("私聊无法使用此功能")
    directives = arg.extract_plain_text()
    if directives in size_mapping:
        async with DALLEImageSize_lock:
            DALLEImageSize = size_mapping[directives]
        await dell_size.finish(f"已设置绘图尺寸为{DALLEImageSize.value}")
    else:
        await dell_size.finish("参数错误，可选参数：小、中、大")


async def draw_image(prompt: str, times: int = 3):
    for _ in range(times - 1):
        cilent = POOL(model="dall-e-3")
        try:
            return await cilent.images.generate(
                model="dall-e-3", prompt=prompt, size=DALLEImageSize.value
            )
        except RateLimitError:
            POOL.RequestLimit(model="dall-e-3", cilent=cilent, timeout=120)
    return await POOL(model="dall-e-3").images.generate(
        model="dall-e-3", prompt=prompt, size=DALLEImageSize.value
    )


async def get_img(img_url: str):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(img_url) as resp:
                result = await resp.read()
    except Exception as e:
        return None

    if not result:
        return None

    return BytesIO(result)


# async def img_img(self, init_images: BytesIO, sizes):
#     # 根据图像创建图像变体
#     f = tempfile.mktemp(suffix=".png")
#     raw_image = Image.open(init_images)
#     raw_image.save(f, format="PNG")
#     async with aiofiles.open(f, "rb") as f:
#         image_data = await f.read()
#     # 构造请求数据
#     data = {"n": 2, "size": sizes, "response_format": "b64_json"}
#     files = {"image": image_data}
#     url = self.url + "/v1/images/variations"
#     return await self.create_image(url=url, data=data, files=files)
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

    try:
        if urls is None and (arg is None or not arg):
            await dall_drawing.finish("请输入要绘制的内容")

        if urls is not None and (urls is None or len(urls) != 1):
            await dall_drawing.finish("您没有给出图片，或者您给出了多张图片")

        await dall_drawing.send("正在绘图，请稍等...", at_sender=True)

        # # 调用DALL·E绘图
        # if urls is not None:
        #     result, success = await dalle.img_img(
        #         await get_img(urls[0]), DALLEImageSize.value
        #     )
        # else:
        #     # 过滤敏感词
        #     prompt = gfw.filter(arg.extract_plain_text())
        #     result, success = await dalle.get_image(prompt, DALLEImageSize.value)
        prompt = arg.extract_plain_text()
        result, success = await draw_image(prompt)
    finally:
        # 无论成功或失败，都从绘图用户列表中删除
        async with drawing_users_lock:
            del drawing_users[user_id]
    response_message = V11Seg.image(result) if success else "绘图失败，请重试"
    await dall_drawing.finish(response_message, at_sender=True)


dall_img_drawing = on_command(
    "垫图", rule=to_me(), aliases={"img_draw"}, priority=2, block=True
)


@dall_img_drawing.handle()
async def _(event: MessageEvent, urls=ImageURLs()):
    await do_drawing(event, urls=urls)
