import hashlib
import re
import base64
import aiohttp
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
async def _(bot: Bot, event: Event):
    uid = hashlib.sha1((bot.adapter.get_name() + event.get_user_id()).encode()).digest()
    if uid not in user_record:
        user_record[uid] = UserRD()
    record = user_record[uid]

    await my_model.finish(f"你的模型是{record.model}")


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
        images.extend([seg.data["url"] for seg in args if seg.type == "image"])
    _chat = [{"type": "text", "text": re.sub(r"!\[.*?\]\((.*?)\)", "", _chat)}]

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
        message = await chat(message=record.chatlog, model=record.model)
        if record.append(message):
            await m_chat.send(f"你的模型变成 {p_config.fallback_model} 了。")
        message = message["choices"][0]["message"]["content"]
        if isinstance(args, V11M):
            message = [
                {
                    "type": "node",
                    "data": {
                        "uin": str(event.get_user_id()),
                        "name": "GPT",
                        "content": V11Seg.text(message),
                    },
                }
            ]
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
