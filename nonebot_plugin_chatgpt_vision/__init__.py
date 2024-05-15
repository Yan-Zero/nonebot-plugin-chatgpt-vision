import hashlib
import re
from datetime import datetime
from datetime import timedelta
from nonebot import get_plugin_config
from nonebot import on_command
from nonebot.adapters import Event
from nonebot.adapters import Bot
from nonebot.adapters import Message
from nonebot.plugin import PluginMetadata
from nonebot.rule import to_me
from nonebot.params import CommandArg
from nonebot.adapters.onebot.v11.message import Message as V11M
from nonebot.adapters.onebot.v11.message import MessageSegment as V11Seg
from nonebot.adapters.onebot.v11.event import GroupMessageEvent as V11GME
from nonebot.adapters.onebot.v11.bot import send as v11send
from nonebot.permission import SUPERUSER

from .config import Config
from .chat import chat
from .chat import get_comsumption


__plugin_meta__ = PluginMetadata(
    name="ChatGPT",
    description="",
    usage="",
    config=Config,
)

p_config: Config = get_plugin_config(Config)


class UserRD:
    chatlog: list
    model: str
    consumption: float
    time: datetime
    count: int

    def __init__(self) -> None:
        self.chatlog = []
        self.time = datetime.now()
        self.consumption = 0
        self.model = p_config.openai_default_model
        self.count = 0

    def check(self) -> bool:
        if self.consumption < p_config.limit_for_single_user:
            return False
        if datetime.now() - self.time > timedelta(days=1):
            self.time = datetime.now()
            self.consumption = 0
            return False
        return True

    def image(self, count: int = 1):
        if self.model.startswith("gpt-4o"):
            self.consumption += 0.003825 * count
        else:
            self.consumption += 0.00765 * count

    def append(self, response) -> bool:
        if "prompt_tokens" in response:
            pt = response["prompt_tokens"]
        else:
            pt = 100

        self.consumption += get_comsumption(response["usage"], response["model"])
        self.count += 1
        self.chatlog.append(response["choices"][0]["message"])

        if pt > p_config.max_history_tokens or self.count >= p_config.max_chatlog_count:
            self.chatlog.pop(0)
            self.model = p_config.fallback_model
            return True
        return False


user_record: dict[bytes, UserRD] = {}

m_chat = on_command("chat", priority=40, force_whitespace=True, block=True)
reset = on_command("reset", priority=40, force_whitespace=True, block=True)


@reset.handle()
async def _(bot: Bot, event: Event):
    uid = hashlib.sha1((bot.adapter.get_name() + event.get_user_id()).encode()).digest()
    if uid not in user_record:
        user_record[uid] = UserRD()
    record = user_record[uid]
    record.chatlog.clear()

    await reset.finish(f"清空了……你已经说了{record.consumption}$的话了。")


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
    images = re.findall(r"!\[.*?\]\((.*?)\)", _chat)
    _chat = [{"type": "text", "text": re.sub(r"!\[.*?\]\((.*?)\)", "", _chat)}]
    if isinstance(args, V11M):
        images.extend([seg.data["url"] for seg in args if seg.type == "image"])
    if images:
        _chat.extend(
            [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": i,
                        "detail": "high",
                    },
                }
                for i in images
            ]
        )

    try:
        record.chatlog.append(
            {
                "role": "user",
                "content": _chat,
            },
        )
        message = await chat(message=record.chatlog, model=record.model)
        if record.append(message):
            await m_chat.send("你的模型变成 3.5 了。")
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
