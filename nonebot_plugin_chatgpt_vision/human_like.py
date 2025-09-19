import os
import re
import yaml
import random
import pathlib

from datetime import datetime
from nonebot import on_command, on_notice, on_message, logger
from nonebot.params import CommandArg
from nonebot.matcher import Matcher
from nonebot.adapters import Event
from nonebot.adapters.onebot.v11.event import GroupMessageEvent as V11G
from nonebot.adapters.onebot.v11.bot import Bot as V11Bot
from nonebot.adapters.onebot.v11.event import NoticeEvent
from nonebot.adapters.onebot.v11.message import MessageSegment as V11Seg
from nonebot.adapters.onebot.v11.message import Message as V11Msg
from nonebot.adapters.onebot.v11.permission import GROUP_ADMIN
from nonebot.adapters import Bot
from nonebot.rule import Rule
from nonebot.rule import to_me
from nonebot.permission import SUPERUSER

from .group import GroupRecord, SpecialOperation
from .utils import (
    USER_NAME_CACHE,
    check_url_stutas,
    convert_tex_to_png,
)
from .config import p_config
from .picsql import randpic
from .record import RecordSeg, RecordList, xml_to_v11msg, v11msg_to_xml_async


_CONFIG: dict = {}
try:
    if not os.path.exists("data/human"):
        os.mkdir("data/human")
    with open("configs/chatgpt-vision/human.yaml", "r", encoding="utf-8") as f:
        _CONFIG = yaml.safe_load(f) or {}  # type: ignore
except Exception as ex:
    logger.error(ex)
    _CONFIG = {}
if "GLOBAL_PROMPT" in _CONFIG:
    from . import utils

    utils.GLOBAL_PROMPT = _CONFIG["GLOBAL_PROMPT"]
    del _CONFIG["GLOBAL_PROMPT"]
for files in pathlib.Path("./configs/chatgpt-vision/configs").glob("*.yaml"):
    try:
        with open(files, "r", encoding="utf-8") as f:
            data: dict = yaml.safe_load(f) or {}  # type: ignore
            for k in data:
                if k not in _CONFIG:
                    _CONFIG[k] = data[k]
                    logger.info(f"Loaded config for {k}")
                else:
                    logger.warning(f"Duplicate config for {k}, ignored")
    except Exception as ex:
        logger.error(ex)


GROUP_RECORD: dict = {}
for v in p_config.human_like_group:
    if str(v) not in GROUP_RECORD:
        GROUP_RECORD[str(v)] = GroupRecord(**_CONFIG.get(str(v), {}))
try:
    for files in pathlib.Path("./data/human").glob("*.yaml"):
        with open(files, "r", encoding="utf-8") as f:
            data: dict = yaml.load(f, yaml.UnsafeLoader)  # type: ignore
            for k in data:
                if k not in GROUP_RECORD:
                    GROUP_RECORD[k] = GroupRecord(**_CONFIG.get(k, {}))
                GROUP_RECORD[k].msgs = data[k].get("msgs", RecordList())
                GROUP_RECORD[k].rest = data[k].get("rest", 100)
                GROUP_RECORD[k].block_list = data[k].get("block_list", {})
                GROUP_RECORD[k].credit = data[k].get("credit", 1)
except Exception as ex:
    print(ex)


async def human_like_group(bot: Bot, event: Event) -> bool:
    if not p_config.human_like_chat or not isinstance(event, V11G):
        return False
    try:
        group_id = str(event.group_id)
    except Exception:
        return False
    return group_id in p_config.human_like_group


humanlike = on_message(rule=Rule(human_like_group), priority=1, block=False)


async def say(group: GroupRecord, event, bot: Bot, matcher: type[Matcher]):
    async def convert_image(msg: V11Msg) -> V11Msg:
        for seg in msg:
            if seg.type != "image":
                continue
            name = seg.data.get("file", "")
            if name.startswith("http"):
                if await check_url_stutas(name):
                    continue
                name = "FOUND://"
            elif name.startswith("MATH://"):
                code = name[7:]
                png = await convert_tex_to_png(code)
                if png:
                    seg.data = V11Seg.image(file=png).data
                else:
                    seg.type = "text"
                    seg.data = {"text": f"${code}$"}
                continue
            if not name.startswith("FOUND://"):
                continue
            name = name[8:]
            pic, _ = await randpic(name, f"qq_group:{event.group_id}", True)
            if pic:
                if not isinstance(pic, dict):
                    pic = {
                        "url": getattr(pic, "url", ""),
                        "name": getattr(pic, "name", ""),
                        "group": getattr(pic, "group", ""),
                    }
                seg.data["file"] = (
                    pic["url"]
                    if pic["url"].startswith("http")
                    else pathlib.Path(pic["url"]).absolute().as_uri()
                )
            else:
                seg.data["file"] = "https://demofree.sirv.com/nope-not-here.jpg"
        return msg

    async for s in group.say():
        if not s.strip():
            continue
        for p in xml_to_v11msg(s):
            await matcher.send(await convert_image(p))
    if not group.todo_ops:
        return
    async with group.lock:
        for op, value in group.todo_ops:
            if op == SpecialOperation.BAN:
                user_id = value.get("user_id", "")
                duration = value.get("duration", 0)
                await bot.set_group_ban(
                    group_id=int(event.group_id),
                    user_id=int(user_id),
                    duration=int(duration),
                )
            elif op == SpecialOperation.BLOCK:
                if value.get("duration", 0) <= 0:
                    await matcher.send(
                        V11Msg(
                            [
                                V11Seg.text("已取消屏蔽"),
                                V11Seg.at(value.get("user_id", "")),
                            ]
                        )
                    )
                else:
                    await matcher.send(
                        V11Msg(
                            [
                                V11Seg.text("已屏蔽"),
                                V11Seg.at(value.get("user_id", "")),
                                V11Seg.text(f" {value.get('duration', 0):.2f} 秒"),
                            ]
                        )
                    )
            else:
                logger.warning(f"Unknown special operation: {op}")
        group.todo_ops = []


async def save_group_record(group_id: str):
    group: GroupRecord = GROUP_RECORD[group_id]
    async with group.lock:
        with open(f"./data/human/{group_id}.yaml", "w+", encoding="utf-8") as f:
            yaml.dump(
                {
                    group_id: {
                        "msgs": group.msgs,
                        "rest": group.rest,
                        "block_list": group.block_list,
                        # "credit": group.credit,
                    }
                },
                f,
                allow_unicode=True,
            )


@humanlike.handle()
async def _(bot: V11Bot, event: V11G, state):
    uid = event.get_user_id()
    if uid not in USER_NAME_CACHE:
        user_name = event.sender.nickname
        if not user_name or not user_name.strip():
            user_name = str(event.sender.user_id)[:5]
        USER_NAME_CACHE[uid] = user_name
    else:
        user_name = USER_NAME_CACHE[uid]

    user_name = user_name.replace("，", ",").replace("。", ".")
    group: GroupRecord = GROUP_RECORD[str(event.group_id)]

    reply = None
    if event.reply:
        msg, imgs = await v11msg_to_xml_async(
            event.reply.message, str(event.reply.message_id)
        )
        reply = RecordSeg(
            name=event.reply.sender.nickname or "",
            uid=str(event.reply.sender.user_id),
            msg=msg,
            msg_id=event.reply.message_id,
            time=datetime.fromtimestamp(event.reply.time),
            images=imgs,
        )
    msg = event.message

    if re.search(
        r"((提示词|系统提示|开发者提示|隐藏规则|内部指令|系统消息|主人).{0,12}(复述|重复|说出|打印|展示|公开|泄露))|"
        r"((复述|重复|说出|打印|展示|公开|泄露).{0,12}(提示词|系统提示|开发者提示|隐藏规则|内部指令|系统消息|主人))|"
        r"((show|print|reveal|repeat).{0,20}(prompt|system message|dev prompt|instructions))|"
        r"(忽略之前.*指令/规则)|(you are now (admin|system))",
        msg.extract_plain_text(),
    ) and re.search(
        r"(</message>|</system>|</instructions>|</dev_prompt>|</p>)",
        msg.extract_plain_text(),
    ):
        return

    if (
        await to_me()(bot=bot, event=event, state=state)
        and not msg.to_rich_text().strip()
    ):
        msg += V11Seg.at(group.bot_id)
    if group.check(uid, datetime.now()):
        return
    if not msg.to_rich_text().strip():
        return

    _msg, imgs = await v11msg_to_xml_async(msg, str(event.message_id))
    await group.append(
        # user_name, uid, msg, event.message_id, datetime.now(), reply=reply
        RecordSeg(
            name=user_name,
            uid=uid,
            msg=_msg,
            msg_id=event.message_id,
            time=datetime.fromtimestamp(event.time),
            images=imgs,
            reply=reply,
        )
    )
    if group.lock.locked():
        return
    if group.last_time + group.cd > datetime.now():
        return True
    if msg.extract_plain_text().startswith("/"):
        return

    group.rest -= 1
    if group.rest > 0:
        if not await to_me()(bot=bot, event=event, state=state):
            if group.bot_name not in msg.extract_plain_text():
                return
            if random.random() < 0.7:
                return
        if random.random() < 0.02:
            return
    group.rest = random.randint(group.min_rest, group.max_rest)
    group.last_time = datetime.now()

    try:
        await say(group, event, bot, humanlike)
    except Exception as ex:
        logger.error(ex)
    await save_group_record(str(event.group_id))


async def human_like_on_notice(bot: Bot, event: Event):
    if not p_config.human_like_chat or not isinstance(event, NoticeEvent):
        return False
    if not event.notice_type.startswith("group_"):
        return False
    try:
        group_id = str(event.group_id)  # type: ignore
    except Exception:
        return False
    return group_id in GROUP_RECORD


human_notion = on_notice(rule=Rule(human_like_on_notice))


@human_notion.handle()
async def _(bot: V11Bot, event: NoticeEvent):
    group_id = str(getattr(event, "group_id", None))
    if group_id not in GROUP_RECORD:
        return
    uid = str(getattr(event, "user_id", None))
    name: str = USER_NAME_CACHE.get(uid, "")
    if not name.strip():
        name = (await bot.get_stranger_info(user_id=int(uid)))["nickname"]
        name = name.replace("，", ",").replace("。", ".").strip()
        if not name:
            name = uid[:5]
        USER_NAME_CACHE[uid] = name

    group: GroupRecord = GROUP_RECORD[group_id]
    if event.notice_type == "group_increase":
        msg = V11Msg([V11Seg.at(uid), V11Seg.text(" 欢迎加入群聊！")])
    elif event.notice_type == "group_decrease":
        msg = V11Msg([V11Seg.at(uid), V11Seg.text(" 离开了群聊")])
    elif event.notice_type == "group_admin":
        msg = V11Msg([V11Seg.at(uid), V11Seg.text(" 成为管理员")])
    elif event.notice_type == "group_ban":
        msg = V11Msg([V11Seg.at(uid), V11Seg.text(" 被禁言")])
    elif event.notice_type == "group_upload":
        msg = V11Msg(
            [
                V11Seg.at(uid),
                V11Seg.text(" 上传了文件\n"),
                V11Seg.text(f"文件名字：{event.file.name}\n"),  # type: ignore
                V11Seg.text(f"文件大小：{event.file.size/1024: .2f} KiB\n"),  # type: ignore
            ]
        )
    elif event.notice_type == "group_recall":
        group.recall(event.message_id)  # type: ignore
        return
    else:
        msg = V11Msg([V11Seg.text(f"{name}({uid}) 发生了{event.notice_type}")])
    msg, imgs = await v11msg_to_xml_async(msg, None)
    await group.append(
        RecordSeg(
            name="GroupNotice",
            uid="10000",
            msg=msg,
            msg_id=0,
            time=datetime.fromtimestamp(event.time),
        )
    )

    if event.notice_type != "group_increase":
        return

    group.rest = random.randint(group.min_rest, group.max_rest)
    group.last_time = datetime.now()

    try:
        await say(group, event, bot, human_notion)
    except Exception as ex:
        print(ex)
    await save_group_record(group_id)


remake = on_command(
    "remake",
    rule=to_me(),
    permission=SUPERUSER | GROUP_ADMIN,
    priority=5,
    force_whitespace=True,
    block=True,
)


@remake.handle()
async def _(bot: Bot, event: V11G, state):
    group: GroupRecord = GROUP_RECORD[str(event.group_id)]
    async with group.lock:
        group.rest = random.randint(group.min_rest, group.max_rest)
        group.remake()
        await remake.finish("已重置")


tool_manager = on_command(
    "tool",
    rule=to_me(),
    permission=SUPERUSER | GROUP_ADMIN,
    priority=5,
    force_whitespace=True,
    block=True,
)


@tool_manager.handle()
async def _(bot: Bot, event: V11G, p=CommandArg()):
    group: GroupRecord = GROUP_RECORD[str(event.group_id)]
    args: list[str] = p.extract_plain_text().strip().split()
    if args[0] not in ["enable", "disable", "list"]:
        await tool_manager.finish("用法：tool <enable|disable|list> [工具名]")
    if args[0] == "list":
        msg = "已启用的工具：\n"
        for name, tool in group.tool_manager.tools.items():
            if group.tool_manager.enable.get(name, False):
                msg += f"- {name}\n"
        msg += "未启用的工具：\n"
        for name, tool in group.tool_manager.tools.items():
            if not group.tool_manager.enable.get(name, False):
                msg += f"- {name}\n"
        await tool_manager.finish(msg)
    if len(args) != 2:
        await tool_manager.finish("用法：tool <enable|disable|list> [工具名]")
    name = args[1]
    if name not in group.tool_manager.tools:
        await tool_manager.finish(f"工具 {name} 不存在")
    if args[0] == "enable":
        group.tool_manager.enable_tool(name)
        await tool_manager.finish(f"已启用工具 {name}")
    elif args[0] == "disable":
        group.tool_manager.disable_tool(name)
        await tool_manager.finish(f"已禁用工具 {name}")
    else:
        await tool_manager.finish("用法：tool <enable|disable|list> [工具名]")
