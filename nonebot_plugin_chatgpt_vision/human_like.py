""" 模仿人类发言的模式"""

import random
import math

from datetime import datetime
from datetime import timedelta
from typing import Any, Dict, Optional
from nonebot import get_plugin_config
from openai import AsyncOpenAI
from nonebot import on_message
from nonebot import on_command
from nonebot.permission import SUPERUSER
from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import GroupMessageEvent as V11GME
from nonebot.adapters import Bot

from .config import Config
from .chat import chat
from .rule import HUMANLIKE_GROUP

p_config: Config = get_plugin_config(Config)

EXP: list = [math.exp(-x / 20) for x in range(p_config.human_like_max_log + 50)]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    l = min(len(a), len(b))
    r = 0
    for i in range(l):
        r += a[i] * b[i]
    return r


class LogWithEmbedding:
    __content: list[tuple[str, int, list[float], datetime]]
    __cilent: AsyncOpenAI
    __sim_matrix: list[list[float]]
    system_prompt: str
    bot_name: str

    def __init__(
        self,
        bot_name: str = "苦咖啡",
        system_prompt: str = "",
        apikey: str = None,
        baseurl: str = None,
    ) -> None:
        self.__content = []
        self.__cilent = AsyncOpenAI(api_key=apikey, base_url=baseurl)
        self.__sim_matrix = []
        self.bot_name = bot_name
        if system_prompt:
            self.system_prompt = system_prompt
        else:
            self.system_prompt = (
                f"Your name is {self.bot_name}. "
                + "You are a group member tring your best"
                + " to imitate other's language style, "
                + "and your every sentence is as succinct as possible."
                + 'If your response is too long, try to add "-?\?-" in the position '
                + "that could spilt it into more parts, which looks like other's style."
            )

    async def append(self, name: str, message: str, time: datetime = datetime.now()):
        """添加消息"""
        msg = f"{name}:\n{message}"
        response = await self.__cilent.embeddings.create(
            input=message, model="text-embedding-3-large"
        )
        self.__content.append(
            (msg, response.usage.total_tokens, response.data[0].embedding, time)
        )
        self.__sim_matrix.append(
            [
                cosine_similarity(response.data[0].embedding, i)
                for _, _, i, _ in self.__cilent
            ]
        )
        self.clear()

    async def say(self) -> list[str]:
        messages = [{"role": "system", "content": self.system_prompt}] + [
            {
                "role": "user",
                "content": i,
            }
            for _, i, _, _ in self.__content
        ]

        msg = []
        for i in (
            (await chat(message=messages, model="gpt-3.5-turbo"))
            .choices[0]
            .message.content.split("-?/?-")
        ):
            if i.startswith(self.bot_name + ":"):
                i = i[: len(self.bot_name + ":")]
            elif i.startswith(self.bot_name + "："):
                i = i[: len(self.bot_name + "：")]
            i = i.strip()
            msg.append(i)
            await self.append(name=self.bot_name, message=i)
        return msg

    def clear(self):
        """清除多余的消息"""
        if (
            len(self.__content) < p_config.human_like_max_log
            and self.total_tokens < p_config.human_like_max_tokens
        ):
            return

        # 保留最近2条
        _min = 100000
        _id = -1
        for i, lc in enumerate(self.__sim_matrix[:-2]):
            t = sum(EXP[abs(j - i)] * c for j, c in enumerate(lc))
            if t < _min:
                _min = t
                _id = i
        if _id >= 0:
            self.__content.pop(_id)
            self.__sim_matrix.pop(_id)
            for i in self.__sim_matrix:
                i.pop(_id)

        self.clear()

    @property
    def total_tokens(self) -> int:
        result = 0
        for _, t, _, _ in self.__content:
            result += t
        return t


__HL = {
    g: LogWithEmbedding(
        apikey=p_config.openai_embedding_apikey,
        baseurl=p_config.openai_embedding_baseurl,
    )
    for g in p_config.human_like_group
}
__LAST_TIME = datetime.now()
__REST = 10

humanlike = on_message(rule=HUMANLIKE_GROUP, priority=1, block=False)


@humanlike.handle()
async def _(bot: Bot, event: V11GME):
    uid = event.get_user_id()
    msg = event.get_message().extract_plain_text()
    group = __HL[event.group_id]
    await group.append(uid, msg)
    __REST -= 1

    if (
        __REST > 0
        and datetime.now() - __LAST_TIME < timedelta(hours=1)
        and random.random() < 0.7
    ):
        return
    __REST = random.randint(1, 8)
    if datetime.now() - __LAST_TIME < timedelta(minutes=1):
        return

    __LAST_TIME = datetime.now()

    try:
        for m in await group.say():
            await humanlike.send(m)
    except Exception as ex:
        print(ex)


if True:
    __hl_test = on_command(cmd="human_test", rule=SUPERUSER, priority=2, block=True)

    @__hl_test.handle()
    async def _(bot: Bot, event: Event):
        try:
            for m in await __HL.say():
                await humanlike.send(m)
        except Exception as ex:
            print(ex)
