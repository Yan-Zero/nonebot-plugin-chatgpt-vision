import hashlib
import yaml
import pypandoc
import asyncio
from PIL import Image
from io import BytesIO
from datetime import datetime
from tex2img import AsyncLatex2PNG
from nonebot import get_plugin_config
from nonebot import on_command
from nonebot.adapters import Event
from nonebot.adapters import Bot
from nonebot.params import CommandArg
from nonebot.adapters.onebot.v11.message import Message as V11M

from nonebot.adapters.onebot.v11.message import MessageSegment as V11Seg
from nonebot.adapters.onebot.v11.event import GroupMessageEvent as V11GME
from nonebot.permission import SUPERUSER

from ..config import Config
from ..chat import chat
from ..chat import error_chat
from ..fee.userrd import UserRD
from ..human_like import RecordSeg

p_config: Config = get_plugin_config(Config)

try:
    with open("./data/user_log.yaml", "r", encoding="utf-8") as f:
        user_record: dict[bytes, UserRD] = yaml.load(f, Loader=yaml.UnsafeLoader)
except Exception:
    user_record: dict[bytes, UserRD] = {}

m_chat = on_command("chat", priority=40, force_whitespace=True, block=True)
reset = on_command("reset", priority=5, force_whitespace=True, block=True)
my_model = on_command("model", priority=5, force_whitespace=True, block=True)
render = AsyncLatex2PNG()

FILE_LOCK: asyncio.Lock = asyncio.Lock()


@reset.handle()
async def _(bot: Bot, event: Event):
    uid = hashlib.sha1((bot.adapter.get_name() + event.get_user_id()).encode()).digest()
    if uid not in user_record:
        user_record[uid] = UserRD()
    record = user_record[uid]
    record.chatlog.clear()
    async with FILE_LOCK:
        with open("./data/user_log.yaml", "w+", encoding="utf-8") as f:
            yaml.dump(user_record, f, allow_unicode=True)
    await reset.finish(f"清空了……你还剩{record.consumption * 7.2}￥的额度。")


@my_model.handle()
async def _(bot: Bot, event: Event, args=CommandArg()):
    uid = hashlib.sha1((bot.adapter.get_name() + event.get_user_id()).encode()).digest()
    if uid not in user_record:
        user_record[uid] = UserRD()
    record = user_record[uid]

    args = args.extract_plain_text().strip()
    if not args:
        await my_model.finish(f"你的模型是{record.model}")

    record.model = args
    await my_model.finish(f"你的模型现在是{args}，请注意，不一定可用。")


async def get_png(tex: str) -> BytesIO:
    tex = tex.replace("\\usepackage{", "\\usepackage{xeCJK}\n\\usepackage{", 1).replace(
        "\\end{document}", "\\pagestyle{empty}\\end{document}"
    )
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
async def _(bot: Bot, event: Event, args: V11M = CommandArg()):
    global model, user_record
    uid = hashlib.sha1((bot.adapter.get_name() + event.get_user_id()).encode()).digest()
    if uid not in user_record:
        user_record[uid] = UserRD()
    record = user_record[uid]
    if record.check() and not (await SUPERUSER(bot, event)):
        await m_chat.finish(f"嗯……你的今日配额莫得了。")

    if not args.to_rich_text().strip():
        await m_chat.finish("你好像什么都没说……")

    def to_str(content: list | str):
        if isinstance(content, str):
            return content
        if isinstance(content, dict):
            if content["type"] == "text":
                return content["text"]
            if content["type"] == "image_url":
                return f"[图片]"
            return str(content)
        if isinstance(content, list):
            return "".join([to_str(i) for i in content])

    _chat = RecordSeg(
        name="A",
        uid="12345",
        msg=args,
        time=datetime.now(),
        msg_id=0,
        reply=event.reply.message if event.reply else None,
    )
    await _chat.fetch(True)
    record.chatlog.append(
        {
            "role": "user",
            "content": _chat.content(image_mode=True),
        },
    )
    try:
        rsp = await chat(message=record.chatlog, model=record.model)
        message = rsp.choices[0].message.content
        if not message:
            await m_chat.send("好像什么都没说……")
            return
        if record.append(rsp.model_dump()):
            await m_chat.send(f"你的模型变成 {p_config.fallback_model} 了。")

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

        async with FILE_LOCK:
            with open("./data/user_log.yaml", "w+", encoding="utf-8") as f:
                yaml.dump(user_record, f, allow_unicode=True)

        message = [
            {
                "type": "node",
                "data": {
                    "uin": "114514",
                    "name": "GPT",
                    "content": i,
                },
            }
            for i in [
                message,
                V11Seg.text(f"你现在上下文有{len(record.chatlog)}条。"),
                V11Seg.text(f"剩余额度{record.consumption * 7.2}￥"),
            ]
        ]
        message = [
            {
                "type": "node",
                "data": {
                    "uin": (
                        str(event.get_user_id()) if i["role"] == "user" else "114514"
                    ),
                    "name": i["role"],
                    "content": V11Seg.text(f"{ i['role']}:\n{to_str(i['content'])}"),
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
                V11Seg.forward(await bot.call_api("send_forward_msg", messages=message))
            )
    except Exception as ex:
        await m_chat.finish(f"出错了哦。{await error_chat(ex)}")
