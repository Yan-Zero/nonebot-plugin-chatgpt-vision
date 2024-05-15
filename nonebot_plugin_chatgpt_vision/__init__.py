import uuid
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


class UserD:
    chatlog: list
    model: str
    consumption: float
    time: datetime

    def __init__(self) -> None:
        self.chatlog = []
        self.time = datetime.now()

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

    def append(self, response):
        if "prompt_tokens" in response:
            pt = response["prompt_tokens"]
        else:
            pt = 100

        self.consumption += get_comsumption(response["usage"], response["model"])
        self.chatlog.append(response["choices"][0]["message"])

        if (
            pt > p_config.max_history_tokens
            or len(self.chatlog) > p_config.max_chatlog_count
        ):
            self.chatlog.pop(0)


user_record: dict[uuid.UUID, UserD] = {}

m_chat = on_command(
    cmd="c", rule=to_me(), force_whitespace=True, block=True, priority=40
)


@m_chat.handle()
async def _(bot: Bot, event: Event, args: Message = CommandArg()):
    global model, user_record
    uid = uuid.uuid5(bot.adapter.get_name(), event.get_user_id())
    if uid not in user_record:
        user_record[uid] = UserD()
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
        message = await chat(record.chatlog)
        record.append(message)
        message = message["choices"][0]["message"]["content"]
        if isinstance(args, V11M):
            await v11send(
                bot=bot,
                event=event,
                reply_message=True,
                message=message,
            )
        else:
            await m_chat.finish(message=message)
    except Exception as ex:
        await m_chat.finish(f"出错了哦。\n\n{ex}")
