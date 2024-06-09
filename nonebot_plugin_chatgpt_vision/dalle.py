import asyncio
import yaml
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
from nonebot.permission import SUPERUSER
from openai import RateLimitError
from openai import BadRequestError

from .chat import POOL
from .chat import chat


class Size(Enum):
    SMALL = "256x256"
    MEDIUM = "512x512"
    LARGE = "1024x1024"


# 全局变量，用于存储DALL·E的开关状态、图片尺寸，以及正在绘图的用户
drawing_users = {}  # 用于存储正在绘图的用户
DALLESwitchState = True  # 开关状态,默认关闭
DALLEPromptState = True  # 开关状态,默认关闭

drawing_users_lock = asyncio.Lock()  # 用于绘图用户的锁
DALLESwitchState_lock = asyncio.Lock()  # 用于保护DALLESwitchState

superusers = get_driver().config.superusers
dall_switch = on_command(
    "开关绘图",
    aliases={"开启绘图", "关闭绘图"},
    permission=SUPERUSER,
    priority=2,
    block=True,
)
dell_llm = on_command(
    "中间llm",
    rule=to_me(),
    permission=SUPERUSER,
    priority=2,
    block=True,
)
dall_drawing = on_command(
    "draw",
    rule=to_me(),
    priority=2,
    block=True,
)


@dall_switch.handle()
async def _(event: MessageEvent):
    global DALLESwitchState  # 在函数内部声明全局变量
    if isinstance(event, PrivateMessageEvent) and str(event.user_id) not in superusers:
        await dall_switch.finish("私聊无法使用此功能")
    if isinstance(event, GroupMessageEvent):
        async with DALLESwitchState_lock:
            DALLESwitchState = not DALLESwitchState
            await dall_switch.finish(
                "已开启绘图功能" if DALLESwitchState else "已关闭绘图功能"
            )


@dell_llm.handle()
async def _(event: MessageEvent):
    global DALLEPromptState  # 在函数内部声明全局变量
    if isinstance(event, PrivateMessageEvent) and str(event.user_id) not in superusers:
        await dell_llm.finish("私聊无法使用此功能")
    if isinstance(event, GroupMessageEvent):
        async with DALLESwitchState_lock:
            DALLEPromptState = not DALLEPromptState
            await dell_llm.finish(
                "已开启中间 LLM" if DALLEPromptState else "已关闭中间 LLM"
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


@dall_drawing.handle()
async def _(event: MessageEvent, arg: Message = CommandArg()):
    await do_drawing(event, arg)


async def do_drawing(event: MessageEvent, arg: Optional[Message] = None):
    global drawing_users
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
        await dall_drawing.send("正在绘图，请稍等...", at_sender=True)
        rsp = arg.extract_plain_text()
        if DALLEPromptState:
            rsp = (
                (
                    await chat(
                        message=[
                            {
                                "role": "user",
                                "content": yaml.safe_dump(
                                    {
                                        "dall-e-3": """Whenever a description of an image is given, create a prompt that dalle can use to generate the image and abide to the following policy:

1. The prompt must be in English. Translate to English if needed.
2. DO NOT ask for permission to generate the image, just do it!
3. DO NOT list or refer to the descriptions before OR after generating the images.
4. Do not create more than 1 image, even if the user requests more.
5. Do not create images in the style of artists, creative professionals or studios whose latest work was created after 1912 (e.g. Picasso, Kahlo).
- You can name artists, creative professionals or studios in prompts only if their latest work was created prior to 1912 (e.g. Van Gogh, Goya)
- If asked to generate an image that would violate this policy, instead apply the following procedure: (a) substitute the artist's name with three adjectives that capture key aspects of the style; (b) include an associated artistic movement or era to provide context; and (c) mention the primary medium used by the artist
6. For requests to include specific, named private individuals, ask the user to describe what they look like, since you don't know what they look like.
7. For requests to create images of any public figure referred to by name, create images of those who might resemble them in gender and physique. But they shouldn't look like them. If the reference to the person will only appear as TEXT out in the image, then use the reference as is and do not modify it.
8. Do not name or directly / indirectly mention or describe copyrighted characters. Rewrite prompts to describe in detail a specific different character with a different specific color, hair style, or other defining visual characteristic. Do not discuss copyright policies in responses.
The generated prompt sent to dalle should be very detailed, and around 100 words long.""",
                                        "user_request": rsp,
                                        "return_format": "yaml",
                                        "response_format": """prompt: ...""",
                                    }
                                ),
                            }
                        ],
                        model="gpt-3.5-turbo",
                    )
                )
                .choices[0]
                .message.content
            )
        try:
            rsp = yaml.safe_load(rsp)
            rsp = rsp["prompt"]
        except Exception:
            rsp = rsp

        result = await draw_image(model="dall-e-3", prompt=rsp)
        result = result.data[0].url
        success = True
    except BadRequestError as bd:
        error = str(bd.message)
    except Exception as ex:
        error = str(ex)
    finally:
        async with drawing_users_lock:
            del drawing_users[user_id]
    response_message = [V11Seg.image(result)] if success else error
    await dall_drawing.finish(response_message, at_sender=True)
