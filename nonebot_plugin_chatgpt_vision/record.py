import io
import yaml
import bisect
import base64
import aiohttp

from lxml import etree  # type: ignore
from PIL import Image
from collections.abc import Iterable
from typing import Any, Optional
from datetime import datetime
from nonebot.adapters.onebot.v11.message import Message as V11Msg
from nonebot.adapters.onebot.v11.message import MessageSegment as V11Seg

from .utils import QFACE
from .picsql import upload_image


PARSER = etree.XMLParser(resolve_entities=False, no_network=True)


async def convert_gif_to_png_base64(url: str) -> str:
    """
    检测并转换GIF图片为PNG格式的base64编码

    Args:
        url: 图片URL

    Returns:
        如果是GIF则返回转换后的base64 data URL，否则返回原URL
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status != 200:
                    return url

                # 只读取前6个字节判断是否为GIF
                header = await response.content.read(6)
                if len(header) < 6 or header[:3] != b"GIF":
                    return url

                # 确认是GIF后，重新请求完整内容
                async with session.get(url) as full_response:
                    if full_response.status != 200:
                        return url

                    content = await full_response.read()

                    # 转换为PNG
                    with Image.open(io.BytesIO(content)) as img:
                        # 转换为RGBA模式并取第一帧
                        img = img.convert("RGBA")

                        # 保存为PNG格式
                        output = io.BytesIO()
                        img.save(output, format="PNG")
                        output.seek(0)

                        # 转换为base64
                        png_data = output.getvalue()
                        base64_data = base64.b64encode(png_data).decode("utf-8")

                        return f"data:image/png;base64,{base64_data}"

    except Exception as e:
        from nonebot import logger

        logger.error(f"GIF转PNG失败: {e}")
        return url

    return url


def v11msg_to_xml(msg: V11Msg, msg_id: str | None) -> tuple[str, list]:
    if msg_id is None:
        ret = "<p>"
    else:
        ret = f'<p msgid="{msg_id}">'
    images = []
    for seg in msg:
        if seg.type == "text":
            ret += seg.data["text"]
        elif seg.type == "at":
            ret += f'<mention id="{seg.data["id"]}">{seg.data["name"]}</mention>'
        elif seg.type == "reply":
            ret += f'<reply id="{seg.data["id"]}"/>'
        elif seg.type == "face":
            ret += f'[face,{QFACE.get(seg.data["id"], "notfound")}]'
        elif seg.type == "image":
            images.append(seg.data["file"])
            ret += "[image]"
        elif seg.type == "mface":
            images.append(seg.data["url"])
            ret += f'[image,{seg.data["summary"][1:-1]}]'
        else:
            ret += f"[{seg.type}]"
    ret += "</p>"
    return ret, images


class RecordSeg:
    name: str
    uid: str
    msg: list[tuple[str, str]]
    """富文本 XML 消息，或yaml存储的内容

    Example:
    <p msgid="1234567890">你好<mention id="123456789">苦咖啡</mention>！</p>

    解析后为 V11Msg([V11Seg.text("你好"), V11Seg.at(123456789, "苦咖啡"), V11Seg.text("！")])
    """
    time: datetime

    reply: Optional["RecordSeg"]
    images: list[str]

    def __init__(
        self,
        name: str,
        uid: str,
        msg: V11Msg | str,
        msg_id: str | int,
        time: datetime,
        images: list[str] = [],
        reply: Optional["RecordSeg"] = None,
    ):
        if images:
            self.images = images
        else:
            self.images = ["FETCH?"]
        self.name = name
        self.uid = uid
        self.msg = []
        if isinstance(msg, V11Msg):
            import warnings

            warnings.warn(
                "RecordSeg.msg should be str, V11Msg is deprecated", DeprecationWarning
            )
            ret, imgs = v11msg_to_xml(msg, str(msg_id))
            self.images.extend(imgs)
            self.msg.append((str(msg_id), ret))
        else:
            self.msg.append((str(msg_id), msg))
        self.time = time
        self.reply = reply

    def __str__(self):
        return self.to_str(with_title=True)

    def to_str(
        self,
        with_title: bool = False,
        with_reply: bool = True,
    ):
        ret = ""
        if with_title:
            ret += (
                "<message>"
                f"<name>{self.name}</name>"
                f"<uid>{self.uid}</uid>"
                f"<time>{self.time.strftime('%Y-%m-%d %H:%M %a')}</time>"
            )
        if self.reply and with_reply:
            ret += (
                "<quote>"
                f"{self.reply.to_str(with_title=True, with_reply=False)}"
                "</quote>"
            )
        return (
            ret + "".join(m[1] for m in self.msg) + ("</message>" if with_title else "")
        )

    def content(self, with_title: bool = False, image_mode: bool = False) -> list | str:
        if not image_mode:
            return self.to_str(with_title)
        if not self.images:
            return self.to_str(with_title)
        ret: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": self.to_str(with_title),
            }
        ]
        for i in self.images:
            ret.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": i,
                    },
                }
            )
        return ret

    async def fetch(self, image_mode: bool = False) -> None:
        if self.reply:
            await self.reply.fetch(image_mode)
            if self.reply.images:
                self.images.extend(self.reply.images)

        if not image_mode:
            return
        if not self.images:
            return
        if self.images[0] != "FETCH?":
            return
        for i in range(len(self.images)):
            url = self.images[i]
            if url == "FETCH?":
                continue
            # 处理GIF转PNG
            url = await convert_gif_to_png_base64(url)
            # 如果不是base64格式，继续原来的上传逻辑
            if not url.startswith("data:"):
                url = await upload_image(url)
            self.images[i] = url
        self.images.pop(0)


class RecordList:
    records: list[RecordSeg]
    merge: bool
    """是否合并相同用户的连续消息"""

    def __init__(self, merge: bool = True, records: list[RecordSeg] = []):
        self.records = records
        self.merge = merge

    def add(self, record: RecordSeg):
        index = bisect.bisect_right(self.records, record.time, key=lambda r: r.time)
        # 判断是否需要合并
        if not self.merge:
            self.records.insert(index, record)
            return
        # 如果有引用消息，不合并
        if not record.reply:
            self.records.insert(index, record)
            return
        # 工具不需要合并
        if record.uid == "tool":
            self.records.insert(index, record)
            return
        # 插入到最前面
        if index == 0:
            self.records.insert(index, record)
            return
        # 合并到前一条
        if record.uid != self.records[index - 1].uid:
            self.records.insert(index, record)
            return
        self.records[index - 1].msg.extend(record.msg)
        self.records[index - 1].images.extend(record.images)
        self.records[index - 1].time = record.time

    def extend(self, records: Iterable[RecordSeg]):
        for record in records:
            self.add(record)

    def recall(self, msg_id: str | int, user_id: str | None = None) -> bool:
        index = -1
        for i, record in enumerate(self.records):
            if user_id and record.uid != user_id:
                continue
            for mid, _ in record.msg:
                if mid == str(msg_id):
                    index = i
                    break
        if index == -1:
            return False
        self.records.pop(index)
        return True

    def message(self, bot_uid: str, image_mode: bool = False) -> list[dict]:
        ret = []
        for record in self.records:
            if record.uid == bot_uid:
                data: dict[str, Any] = {
                    "role": "assistant",
                }
                for id, value in record.msg:
                    data[id] = yaml.safe_load(value)
                ret.append(data)
                continue
            if record.uid == "tool":
                id, content = record.msg[0]
                ret.append(
                    {
                        "role": "tool",
                        "name": record.name,
                        "content": content,
                        "tool_call_id": id,
                    }
                )
                continue
            ret.append(
                {
                    "role": "user",
                    "content": record.content(with_title=True, image_mode=image_mode),
                }
            )
        return ret

    def __len__(self):
        return len(self.records)

    def __getitem__(self, index: int) -> RecordSeg:
        return self.records[index]

    def pop(self, index: int) -> RecordSeg:
        return self.records.pop(index)


XML_PROMPT = """Here is a message in XML format. The message may contain text, mentions, replies, and images.
<p> tags represent paragraphs of text.
<mention> tags represent mentions of users, with an "id" attribute for the user ID and the text content being the user's name.
<reply> tags represent replies to other messages, with an "id" attribute for the message ID being replied to.
<image> tags represent images, with a "name" attribute for the image name.

你的回复应该类似于：
<p>这是真的吗？<mention id="114514"/></p>
<p><image name="笑"/></p>

我们一般推荐多分段，因为单段如果太长容易造成他人阅读困难等。记得你的回复需要正确转义 XML 相关的符号。

"""


def xml_to_v11msg(xml: str) -> Iterable[V11Msg]:
    """
    将 XML 格式的消息转换为 OneBot V11 消息格式

    Args:
        xml: XML 格式的消息字符串

    Returns:
        转换后的 OneBot V11 消息对象
    """
    try:
        root = etree.fromstring(f"<root>{xml}</root>", parser=PARSER)
    except etree.XMLSyntaxError:
        yield V11Msg([V11Seg.text(xml)])
        return

    def _segments_from_p(p) -> list[V11Seg]:
        """把一个 <p> 元素转换为 V11 段列表"""
        segments: list[V11Seg] = []
        if p.text:
            segments.append(V11Seg.text(p.text))

        for sub in p:
            if sub.tag == "mention":
                uid = int(sub.get("id", "10001"))
                segments.append(V11Seg.at(uid))
                if sub.tail:
                    segments.append(V11Seg.text(sub.tail))

            elif sub.tag == "reply":
                mid = int(sub.get("id", "0"))
                segments.append(V11Seg.reply(mid))
                if sub.tail:
                    segments.append(V11Seg.text(sub.tail))

            elif sub.tag == "image":
                name = sub.get("name", "image")
                segments.append(V11Seg.image(file=f"FOUND://{name}"))
                if sub.tail:
                    segments.append(V11Seg.text(sub.tail))

            elif sub.tag in {"time", "name", "uid"}:
                # 标签本身忽略，仅拼接其后续文本
                if sub.tail:
                    segments.append(V11Seg.text(sub.tail))

            else:
                # 未知子标签整体当作文本
                segments.append(V11Seg.text(etree.tostring(sub, encoding="unicode")))
                if sub.tail:
                    segments.append(V11Seg.text(sub.tail))

        return segments

    ps = list(root.iter("p"))
    if ps:
        for p in ps:
            segs = _segments_from_p(p)
            # 避免产出空消息
            if segs:
                yield V11Msg(segs)
        return

    # 兼容路径：没有任何 <p>，按照原先的“所有节点合成一条消息”
    segments = []
    for elem in root.iter():
        if elem.tag == "root":
            continue
        elif elem.tag == "p":
            # 正常不会到这里（因为上面 ps 为空），但留作稳妥
            segments.extend(_segments_from_p(elem))
        else:
            # 非 <p> 标签整体当文本
            segments.append(V11Seg.text(etree.tostring(elem, encoding="unicode")))
            if elem.tail:
                segments.append(V11Seg.text(elem.tail))

    if segments:
        yield V11Msg(segments)
