""" 模仿人类发言的模式"""

import random
import re
import yaml
import pathlib
import asyncio
import os
from datetime import datetime
from datetime import timedelta
from nonebot import get_plugin_config
from nonebot import on_message
from nonebot import on_command
from nonebot import on_notice
from nonebot.adapters import Event
from nonebot.adapters.onebot.v11.event import GroupMessageEvent as V11G
from nonebot.adapters.onebot.v11.bot import Bot as V11Bot
from nonebot.adapters.onebot.v11.bot import send
from nonebot.adapters.onebot.v11.event import NoticeEvent
from nonebot.adapters.onebot.v11.message import MessageSegment as V11Seg
from nonebot.adapters.onebot.v11.message import Message as V11Msg
from nonebot.adapters.onebot.v11.permission import GROUP_ADMIN
from nonebot.adapters import Bot
from nonebot.rule import Rule
from nonebot.params import CommandArg
from nonebot.rule import to_me
from nonebot.permission import SUPERUSER

from .config import Config
from .picsql import randpic
from .group import GroupRecord
from .group import RecordSeg
from .group import CACHE_NAME
from .group import seg2text

p_config: Config = get_plugin_config(Config)
_CONFIG = None
try:
    if not os.path.exists("data/human"):
        os.mkdir("data/human")
    with open("configs/chatgpt-vision/human.yaml", "r", encoding="utf-8") as f:
        _CONFIG = yaml.safe_load(f) or {}
except Exception:
    _CONFIG = {}

GROUP_RECORD: dict = {}
for v in p_config.human_like_group:
    if str(v) not in GROUP_RECORD:
        GROUP_RECORD[str(v)] = GroupRecord(**_CONFIG.get(str(v), {}))
try:
    for files in pathlib.Path("./data/human").glob("*.yaml"):
        with open(files, "r", encoding="utf-8") as f:
            data = yaml.load(f, yaml.UnsafeLoader)
            for k in data:
                if k not in GROUP_RECORD:
                    GROUP_RECORD[k] = GroupRecord(**_CONFIG.get(k, {}))
                GROUP_RECORD[k].msgs = data[k].get("msgs", [])
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


async def parser_msg(msg: str, group: GroupRecord, event: Event, bot: Bot):
    msg = re.sub(r"@(.+?)\((\d+)\)", r"[CQ:at,qq=\2]", msg)
    for i in re.finditer(r"\[block,(.*?)\((\d+)\)\,\s*(\d+)\]", msg):
        if not (await GROUP_ADMIN(bot=bot, event=event)):
            group.block(i.group(2), i.group(3))
            msg = msg.replace(
                i.group(0),
                f"[CQ:at,qq={i.group(2)}] 屏蔽{i.group(3)}秒",
            )
        else:
            msg = msg.replace(
                i.group(0), f"尝试屏蔽[CQ:at,qq={i.group(2)}]，但是很显然对管理无效。"
            )
    for i in re.finditer(r"\[block,(.*?)\((\d+)\)\]", msg):
        if not (await GROUP_ADMIN(bot=bot, event=event)):
            group.block(i.group(2))
            msg = msg.replace(
                i.group(0),
                f"[CQ:at,qq={i.group(2)}] 屏蔽{group.delta}秒",
            )
        else:
            msg = msg.replace(
                i.group(0), f"尝试屏蔽[CQ:at,qq={i.group(2)}]，但是很显然对管理无效。"
            )
    for i in re.finditer(r"\[unblock,(.*?)\((\d+)\)\]", msg):
        group.block(i.group(2), 1)
    msg = re.sub(
        r"\[unblock,(.*?)\((\d+)\)\]",
        r"解除屏蔽[CQ:at,qq=\2]",
        msg,
    )
    for i in re.finditer(r"\[image,(.+?)\]", msg):
        pic, _ = await randpic(i.group(1), f"qq_group:{event.group_id}", True)
        if pic:
            msg = msg.replace(
                f"[image,{i.group(1)}]",
                f"[CQ:image,file={pic.url if pic.url.startswith('http') else pathlib.Path(pic.url).absolute().as_uri()}]",
                1,
            )
        else:
            msg = msg.replace(f"[image,{i.group(1)}]", f"[{i.group(1)} Not Found]")
    return msg


@humanlike.handle()
async def _(bot: Bot, event: V11G, state):

    uid = event.get_user_id()
    if uid not in CACHE_NAME:
        user_name = event.sender.nickname
        if not user_name or not user_name.strip():
            user_name = str(event.sender.user_id)[:5]
        CACHE_NAME[uid] = user_name
    else:
        user_name = CACHE_NAME[uid]
    user_name = user_name.replace("，", ",").replace("。", ".")
    group: GroupRecord = GROUP_RECORD[str(event.group_id)]

    msg = event.message
    reply = None
    if event.reply:
        reply = RecordSeg(
            name=event.reply.sender.nickname,
            uid=event.reply.sender.user_id,
            msg=event.reply.message,
            msg_id=event.reply.message_id,
            time=datetime.fromtimestamp(event.reply.time),
        )
    if (
        await to_me()(bot=bot, event=event, state=state)
        and not event.message.to_rich_text().strip()
    ):
        msg += V11Seg.at(group.bot_id)
    await group.append(
        user_name, uid, msg, event.message_id, datetime.now(), reply=reply
    )
    if group.check(uid, datetime.now()):
        return
    if group.lock.locked():
        return
    if group.last_time + timedelta(seconds=group.cd) > datetime.now():
        return True
    if event.message.extract_plain_text().startswith("/"):
        return
    if not event.message.to_rich_text().strip():
        return

    group.rest -= 1
    if group.rest > 0:
        if not await to_me()(bot=bot, event=event, state=state):
            return
        elif random.random() < 0.02:
            return
    group.rest = random.randint(group.min_rest, group.max_rest)
    group.last_time = datetime.now()

    try:
        p = await group.say()
        async with group.lock:
            for s in p:
                if s == "[NULL]":
                    continue
                await humanlike.send(V11Msg(await parser_msg(s, group, event, bot=bot)))
    except Exception as ex:
        print(ex)

    async with group.lock:
        with open(f"./data/human/{event.group_id}.yaml", "w+", encoding="utf-8") as f:
            yaml.dump(
                {
                    str(event.group_id): {
                        "msgs": group.msgs,
                        "rest": group.rest,
                        "block_list": group.block_list,
                        "credit": group.credit,
                    }
                },
                f,
                allow_unicode=True,
            )


async def human_like_on_notice(bot: Bot, event: Event):
    if not p_config.human_like_chat or not isinstance(event, NoticeEvent):
        return False
    if not event.notice_type.startswith("group_"):
        return False
    try:
        group_id = str(event.group_id)
    except Exception as ex:
        return False
    return group_id in GROUP_RECORD


human_notion = on_notice(rule=Rule(human_like_on_notice))


@human_notion.handle()
async def _(bot: V11Bot, event: NoticeEvent):
    group_id = str(event.group_id)
    if group_id not in GROUP_RECORD:
        return
    uid = str(event.user_id)
    name: str = CACHE_NAME.get(uid, "")
    if not name.strip():
        name = (await bot.get_stranger_info(user_id=uid))["nickname"]
        name = name.replace("，", ",").replace("。", ".").strip()
        if not name:
            name = uid[:5]
        CACHE_NAME[uid] = name

    group: GroupRecord = GROUP_RECORD[group_id]
    if event.notice_type == "group_increase":
        msg = f"@{name}({uid}) 加入了群聊"
    elif event.notice_type == "group_decrease":
        msg = f"@{name}({uid}) 离开了群聊"
    elif event.notice_type == "group_admin":
        msg = f"@{name}({uid}) 成为管理员"
    elif event.notice_type == "group_ban":
        msg = f"@{name}({uid}) 被禁言"
    elif event.notice_type == "group_upload":
        msg = (
            f"@{name}({uid}) 上传了文件\n"
            + f"文件名字：{event.file.name}\n"
            + f"文件大小：{event.file.size/1024: .2f} KiB\n"
        )
    elif event.notice_type == "group_recall":
        msg = "[NULL]"
        group.recall(event.message_id)
    else:
        msg = f"{name}({uid}) 发生了{event.notice_type}"
    await group.append("GroupNotice", "10000", msg, 0, datetime.now())

    if group.check("10000", datetime.now()):
        return
    group.rest -= 1
    if group.rest > 0:
        if event.notice_type != "group_increase":
            return
    group.rest = random.randint(group.min_rest, group.max_rest)
    group.last_time = datetime.now()

    try:
        p = await group.say()
        async with group.lock:
            for s in p:
                if s == "[NULL]":
                    continue
                await humanlike.send(V11Msg(await parser_msg(s, group, event, bot=bot)))
    except Exception as ex:
        print(ex)

    async with group.lock:
        with open(f"./data/human/{group_id}.yaml", "w+", encoding="utf-8") as f:
            yaml.dump(
                {
                    group_id: {
                        "msgs": group.msgs,
                        "rest": group.rest,
                        "block_list": group.block_list,
                        "credit": group.credit,
                    }
                },
                f,
                allow_unicode=True,
            )


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


credit = on_command(
    "额度",
    rule=to_me(),
)


@credit.handle()
async def _(bot: Bot, event: V11G, state):
    group: GroupRecord = GROUP_RECORD[str(event.group_id)]
    await credit.finish(f"剩余额度：{group.credit*7.2: .3f}￥")


dall_draw = on_command("画", rule=to_me(), aliases={"draw"})


@dall_draw.handle()
async def _(bot: Bot, event: V11G, arg=CommandArg()):
    group_id = str(event.group_id)
    if group_id not in GROUP_RECORD:
        return
    group: GroupRecord = GROUP_RECORD[group_id]
    if not group.draw_enable:
        await dall_draw.finish("绘图功能未开启")
    uid = str(event.user_id)
    if group.check(uid, datetime.now()):
        return
    p = arg.extract_plain_text().strip()
    if not p:
        await dall_draw.finish("请输入内容")
    s, u = await group.draw_dall(
        p,
        uid,
    )
    if s:
        await send(bot, event=event, message=V11Seg.image(u), reply_message=True)
    else:
        await dall_draw.finish(u)


sd_drawing = on_command(
    "sd",
    rule=to_me(),
    priority=2,
    block=True,
)


@sd_drawing.handle()
async def _(bot: Bot, event: V11G, arg=CommandArg()):
    group_id = str(event.group_id)
    if group_id not in GROUP_RECORD:
        return
    group: GroupRecord = GROUP_RECORD[group_id]
    if not group.draw_enable:
        await sd_drawing.finish("绘图功能未开启")
    uid = str(event.user_id)
    if group.check(uid, datetime.now()):
        return
    p: str = arg.extract_plain_text().strip()
    if not p:
        await sd_drawing.finish("请输入内容")
    p = p.split("\n\n")
    s, u = await group.draw_sd(
        p[0],
        p[1] if len(p) > 1 else "",
        uid,
    )
    if s:
        await send(bot, event=event, message=V11Seg.image(u), reply_message=True)
    else:
        await sd_drawing.finish(u)


dall_switch = on_command(
    "开关绘图",
    aliases={"开启绘图", "关闭绘图"},
    permission=SUPERUSER | GROUP_ADMIN,
    priority=2,
    block=True,
)


@dall_switch.handle()
async def _(event: V11G):
    group_id = str(event.group_id)
    if group_id not in GROUP_RECORD:
        return
    group: GroupRecord = GROUP_RECORD[group_id]

    group.draw_enable = not group.draw_enable
    await dall_switch.finish(
        "已开启绘图功能" if group.draw_enable else "已关闭绘图功能"
    )
