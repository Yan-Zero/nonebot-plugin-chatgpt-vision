import yaml
import pathlib

from copywrite import generate_copywrite
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

from .chat import POOL
from .chat import chat

superusers = get_driver().config.superusers
read = on_command(
    "read",
    rule=to_me(),
    priority=5,
    force_whitespace=True,
    block=True,
)
copywrite = on_command(
    "copywrite",
    aliases={"文案"},
    priority=5,
    force_whitespace=True,
    block=True,
)


@read.handle()
async def _(event: MessageEvent, args=CommandArg()):
    if isinstance(event, PrivateMessageEvent) and str(event.user_id) not in superusers:
        await read.finish("私聊无法使用此功能")
    if isinstance(event, V11GME):
        if not event.reply:
            await read.finish("请先回复一条消息")
        try:
            rsp = await POOL("tts-1-hd").audio.speech.create(
                model="tts-1-hd",
                voice="onyx",
                input=event.reply.message.extract_plain_text(),
            )
            await read.send(V11Seg.record(await rsp.aread()))
        except Exception as ex:
            await read.finish(f"发生错误: {ex}")


_copy: dict[str, dict] = {}
for file in pathlib.Path("./data/copywrite").glob("**/*.yaml"):
    with open(file, "r", encoding="utf-8") as f:
        _data = yaml.safe_load(f)
        if isinstance(_data, dict):
            _copy.update(_data)
for file in pathlib.Path(__file__).parent.glob("copywrite/*.yaml"):
    with open(file, "r", encoding="utf-8") as f:
        _data = yaml.safe_load(f)
        if isinstance(_data, dict):
            _copy.update(_data)


@copywrite.handle()
async def _(event: MessageEvent, args=CommandArg()):
    args = args.extract_plain_text().strip()
    if not args:
        ret = "请输入要仿写的文案名字"
        if True:
            ret = "目前的可用文案有：\n" + ", ".join(_copy.keys())
        await copywrite.finish(ret)

    args = args.split(maxsplit=1)
    args[0] = args[0].lower()
    if args[0] not in _copy:
        await copywrite.finish("没有找到该文案")

    copy = _copy[args[0]]
    if len(args) == 1:
        await copywrite.finish(copy.get("help", "主题呢？"))

    args = args[1].split(maxsplit=copy.get("keywords", 0))
    if len(args) < copy.get("keywords", 0):
        await copywrite.finish(
            copy.get("help", f'需要有{copy.get("keywords", 0)}个关键词')
        )

    try:
        rsp = await chat(
            message=[
                {
                    "role": "user",
                    "content": generate_copywrite(
                        copy=copy,
                        topic=args[-1],
                        keywords=args[:-1],
                    ),
                }
            ],
            model=copy.get("model", "gpt-3.5-turbo"),
        )
        if not rsp:
            raise ValueError("The Response is Null.")
        if not rsp.choices:
            raise ValueError("The Choice is Null.")
        rsp = rsp.choices[0].message.content
    except Exception as ex:
        await copywrite.finish(f"发生错误: {ex}")
    else:
        await copywrite.finish(rsp)
