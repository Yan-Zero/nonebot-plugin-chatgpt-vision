import hashlib
import re
import base64
import aiohttp
import pypandoc
from PIL import Image
from io import BytesIO
from tex2img import AsyncLatex2PNG
from nonebot import get_plugin_config
from nonebot import on_command
from nonebot.adapters import Event
from nonebot.adapters import Bot
from nonebot.adapters import Message
from nonebot.plugin import PluginMetadata
from nonebot.params import CommandArg
from nonebot.adapters.onebot.v11.message import Message as V11M

from nonebot.adapters.onebot.v11.message import MessageSegment as V11Seg
from nonebot.adapters.onebot.v11.event import GroupMessageEvent as V11GME
from nonebot.permission import SUPERUSER

from .config import Config
from .chat import chat
from .userrd import UserRD
from .dalle import DALLESwitchState
from .misc import copywrite

__plugin_meta__ = PluginMetadata(
    name="ChatGPT",
    description="",
    usage="",
    config=Config,
)

p_config: Config = get_plugin_config(Config)


user_record: dict[bytes, UserRD] = {}

m_chat = on_command("chat", priority=40, force_whitespace=True, block=True)
reset = on_command("reset", priority=5, force_whitespace=True, block=True)
my_model = on_command("my_model", priority=5, force_whitespace=True, block=True)
render = AsyncLatex2PNG()


async def send_image_as_base64(url: str):
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                b64_encoded = base64.b64encode(await response.read()).decode("utf-8")
                return f"data:image/jpeg;base64,{b64_encoded}"
            else:
                return None


@reset.handle()
async def _(bot: Bot, event: Event):
    uid = hashlib.sha1((bot.adapter.get_name() + event.get_user_id()).encode()).digest()
    if uid not in user_record:
        user_record[uid] = UserRD()
    record = user_record[uid]
    record.chatlog.clear()

    await reset.finish(f"清空了……你已经说了{record.consumption}$的话了。")


@my_model.handle()
async def _(bot: Bot, event: Event, args=CommandArg()):
    uid = hashlib.sha1((bot.adapter.get_name() + event.get_user_id()).encode()).digest()
    if uid not in user_record:
        user_record[uid] = UserRD()
    record = user_record[uid]

    args = args.extract_plain_text().strip()
    if not args:
        await my_model.finish(f"你的模型是{record.model}")

    if await SUPERUSER(bot, event):
        if args == "gpt4":
            args = "gpt-4-turbo"
        record.model = args
        await my_model.finish(f"你的模型现在是{args}")
    else:
        await my_model.finish("你没有权限修改模型。")


async def get_png(tex: str) -> BytesIO:
    tex = tex.replace("\\usepackage{", "\\usepackage{xeCJK}\n\\usepackage{", 1).replace(
        "\\end{document}", "\\pagestyle{empty}\\end{document}"
    )
    #     if "\\begin{document}" not in tex:
    #         tex = (
    #             """\\documentclass{article}
    # \\usepackage{xeCJK}
    # \\usepackage{tikz}
    # \\usepackage{pgfplots}
    # \\usepackage{amsmath}
    # \\usepackage{amssymb}
    # \\begin{document}
    # \\pagestyle{empty}
    # """
    #             + tex
    #             + """
    # \\end{document}
    # """
    #         )
    png = Image.open(BytesIO((await render.acompile(tex, compiler="xelatex"))[0]))
    pixels = png.load()
    w, h = png.size
    t, le = 0, 0
    flag = False
    for i in range(0, h):
        for j in range(0, w):
            if pixels[j, i] != (255, 255, 255):
                t = max(0, i - 5)
                flag = True
                break
        if flag:
            break

    flag = False
    for j in range(0, w):
        for i in range(t, h):
            if pixels[j, i] != (255, 255, 255):
                le = max(0, j - 5)
                flag = True
                break
        if flag:
            break
    flag = False

    for i in range(h - 1, t - 1, -1):
        for j in range(le, w):
            if pixels[j, i] != (255, 255, 255):
                h = i + 5
                flag = True
                break
        if flag:
            break

    flag = False
    for j in range(w - 1, le - 1, -1):
        for i in range(t, h):
            if pixels[j, i] != (255, 255, 255):
                w = j + 5
                flag = True
                break
        if flag:
            break
    byte = BytesIO()
    png.crop((le, t, w, h)).save(byte, "PNG")
    return byte


@m_chat.handle()
async def _(bot: Bot, event: Event, args: Message = CommandArg()):
    global model, user_record
    uid = hashlib.sha1((bot.adapter.get_name() + event.get_user_id()).encode()).digest()
    if uid not in user_record:
        user_record[uid] = UserRD()
    record = user_record[uid]
    if record.check() and not (await SUPERUSER(bot, event)):
        await m_chat.finish(
            f"嗯……你已经说了至少{p_config.limit_for_single_user}$的话了。"
        )

    _chat = args.extract_plain_text().strip()
    images = [
        [
            await send_image_as_base64(url)
            for url in re.findall(r"!\[.*?\]\((.*?)\)", _chat)
        ]
    ]
    if isinstance(args, V11M):
        images.extend(
            [
                await send_image_as_base64(seg.data["url"])
                for seg in args
                if seg.type == "image"
            ]
        )
        if event.reply:
            images.extend(
                [
                    await send_image_as_base64(seg.data["url"])
                    for seg in event.reply.message
                    if seg.type == "image"
                ]
            )
    _chat = [{"type": "text", "text": re.sub(r"!\[.*?\]\((.*?)\)", "", _chat)}]

    def to_str(content: list | str):
        if isinstance(content, str):
            return content
        if isinstance(content, dict):
            if content["type"] == "text":
                return content["text"]
            if content["type"] == "image_url":
                return f"[图片]"
                # return f"[图片]({content['image_url']['url']})"
            return str(content)
        if isinstance(content, list):
            return "".join([to_str(i) for i in content])

    try:
        if images:
            _chat.extend(
                [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": i,
                        },
                    }
                    for i in images
                    if i
                ]
            )
        record.chatlog.append(
            {
                "role": "user",
                "content": _chat,
            },
        )
        rsp = await chat(message=record.chatlog, model=record.model)
        if record.append(rsp.model_dump()):
            await m_chat.send(f"你的模型变成 {p_config.fallback_model} 了。")
        print(rsp.choices)
        message = rsp.choices[0].message.content
        print("B")
        if isinstance(args, V11M):
            if "$" in message or "\\[" in message or "\\(" in message:
                try:
                    message = [
                        V11Seg.image(
                            await get_png(
                                pypandoc.convert_text(
                                    message,
                                    "latex",
                                    format="markdown+tex_math_single_backslash",
                                    extra_args=("--standalone",),
                                    # ),
                                )
                            )
                        ),
                        V11Seg.text(message),
                    ]
                except Exception as ex:
                    message = V11Seg.text(message)
            else:
                message = V11Seg.text(message)
            message = [
                {
                    "type": "node",
                    "data": {
                        "uin": str(event.get_user_id()),
                        "name": "GPT",
                        "content": i,
                    },
                }
                for i in [
                    message,
                    V11Seg.text(f"你现在上下文有{len(record.chatlog)}条。"),
                    V11Seg.text(f"总共花费{record.consumption}$"),
                ]
            ]
            message = [
                {
                    "type": "node",
                    "data": {
                        "uin": str(event.get_user_id()),
                        "name": i["role"],
                        "content": V11Seg.text(f"{i['role']}:\n{to_str(i['content'])}"),
                    },
                }
                for i in record.chatlog[:-1]
            ] + message
            if isinstance(event, V11GME):
                await bot.call_api(
                    "send_group_forward_msg",
                    group_id=event.group_id,
                    messages=message,
                )
            else:
                await m_chat.send(
                    V11Seg.forward(
                        await bot.call_api("send_forward_msg", messages=message)
                    )
                )
        else:
            await m_chat.send(message=message)
    except Exception as ex:
        await m_chat.finish(f"出错了哦。\n\n{ex}")
