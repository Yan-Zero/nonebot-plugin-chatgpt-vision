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


async def v11msg_to_xml_async(
    msg: V11Msg, msg_id: Optional[str]
) -> tuple[str, list[str]]:

    # 用于把顺序文本正确放入 parent.text / last_child.tail
    def _append_text(parent: etree._Element, text: str):
        if not text:
            return
        children = list(parent)
        if not children:
            parent.text = (parent.text or "") + text
        else:
            last = children[-1]
            last.tail = (last.tail or "") + text

    # 创建根 <p>
    p = etree.Element("p")
    if msg_id is not None:
        p.set("msgid", msg_id)

    images: list[str] = []

    for seg in msg:
        st = seg.type
        data = seg.data

        if st == "text":
            _append_text(p, data.get("text", ""))

        elif st == "at":
            # <mention uid="...">可选 name</mention>
            uid = str(data.get("qq", ""))
            mention = etree.SubElement(p, "mention")
            mention.set("uid", uid)
            name = data.get("name")
            if name is not None:
                # 放到子元素文本中
                mention.text = name

        elif st == "reply":
            # <reply id="..."/>
            rid = str(data.get("id", ""))
            reply = etree.SubElement(p, "reply")
            reply.set("id", rid)

        elif st == "face":
            # <image name="笑" url="FACE://..."/>
            face_id = data.get("id")
            name = QFACE.get(face_id, f"表情{face_id}")
            face = etree.SubElement(p, "image")
            face.set("name", name)
            face.set("url", f"FACE://{face_id}")
        elif st == "image":
            # <image name="..."/> 或 <image url="..."/>
            file_ = data.get("file")
            if file_:
                url = file_
                if file_.startswith(
                    "https://multimedia.nt.qq.com.cn"
                ) or file_.startswith("http://multimedia.nt.qq.com.cn"):
                    # 处理GIF转PNG
                    url = await convert_gif_to_png_base64(file_)
                    file_ = await upload_image(url)
                    if not url.startswith("data:"):
                        url = file_
                images.append(url)
            image = etree.SubElement(p, "image")
            if file_:
                image.set("url", file_)

        elif st == "mface":
            url = data.get("url")
            if url:
                images.append(url)
            summary = data.get("summary", "")
            if (
                isinstance(summary, str)
                and len(summary) >= 2
                and summary[0] == "["
                and summary[-1] == "]"
            ):
                summary_inner = summary[1:-1]
            else:
                summary_inner = summary
            image = etree.SubElement(p, "image")
            if summary_inner:
                image.set("name", summary_inner)
            if url:
                image.set("url", url)

        else:
            _append_text(p, f"[{st}]")

    xml_str = etree.tostring(p, encoding="unicode")

    return xml_str, images


class RecordSeg:
    name: str
    uid: str
    msg: list[tuple[str, str]]
    """富文本 XML 消息，或yaml存储的内容

    Example:
    <p msgid="1234567890">你好<mention uid="123456789">苦咖啡</mention>！</p>

    解析后为 V11Msg([V11Seg.text("你好"), V11Seg.at(123456789, "苦咖啡"), V11Seg.text("！")])
    """
    time: datetime

    reply: Optional["RecordSeg"]
    images: list[str]

    def __init__(
        self,
        name: str,
        uid: str,
        msg: str,
        msg_id: str | int,
        time: datetime,
        images: list[str] = [],
        reply: Optional["RecordSeg"] = None,
    ):
        if images:
            self.images = images
        else:
            self.images = []
        self.name = name
        self.uid = uid
        self.msg = []
        if isinstance(msg, str):
            self.msg.append((str(msg_id), msg))
        else:
            raise ValueError("msg must be a string")
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


class RecordList:
    records: list[RecordSeg]
    merge: bool
    """是否合并相同用户的连续消息"""

    def __init__(self, merge: bool = True, records: list[RecordSeg] = []):
        if not records:
            records = []
        self.records = records
        self.merge = merge

    def add(self, record: RecordSeg):
        index = bisect.bisect_right(self.records, record.time, key=lambda r: r.time)
        # 判断是否需要合并
        if not self.merge:
            self.records.insert(index, record)
            return
        # 如果有引用消息，不合并
        if record.reply:
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
<mention> tags represent mentions of users, with an "uid" attribute for the user ID and the text content being the user's name.
<reply> tags represent replies to other messages, with an "id" attribute for the message ID being replied to。注意，reply标签是自闭合的，没有内容。一个p tag内只能有一个reply标签，且必须在最前面。
<image> tags represent images, with a "name" attribute for the image name. 另外，image标签也是自闭合的，没有内容。如果你想发的是互联网上的照片，则请设定 url 属性，属性值为图片的 URL，例如<image url="https://example.com/image.png"/>。

你的回复应该类似于：
<p><reply id="-1696903780"/>这是真的吗？<mention uid="114514"/></p>
<p><image name="笑"/></p>
<p>我觉得{x ∈ Z | 1 ≤ x &le; 10}的阶是10才对</p>

我们一般推荐多分段，因为单段如果太长容易造成他人阅读困难等。记得你的回复需要正确转义 XML 相关的符号，特别是 & < > " ' 等符号。
<p>标签外的内容会被忽略，也就是说一切内容都必须放在<p>标签内，并且p tag不允许嵌套。

WARNING: p tag 内的文本内容，特别是数学公式等包含大于、小于号的内容，必须正确转义，否则会导致 XML 解析失败。
WARNING: p tag 内的文本内容，特别是数学公式等包含大于、小于号的内容，必须正确转义，否则会导致 XML 解析失败。


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
        root = etree.fromstring(
            f"<root>{xml}</root>",
            parser=etree.XMLParser(resolve_entities=False, no_network=True),
        )
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
                uid = int(sub.get("uid", "10001"))
                segments.append(V11Seg.at(uid))
                if sub.tail:
                    segments.append(V11Seg.text(sub.tail))
            elif sub.tag == "reply":
                mid = int(sub.get("id", "0"))
                segments.append(V11Seg.reply(mid))
                if sub.text:
                    segments.append(V11Seg.text(sub.text))
                if sub.tail:
                    segments.append(V11Seg.text(sub.tail))
            elif sub.tag == "image":
                name = sub.get("name", None)
                url = sub.get("url", None)
                if url:
                    if url.startswith("http"):
                        segments.append(V11Seg.image(file=url))
                    elif url.startswith("FACE://"):
                        face_id = url[7:]
                        if face_id.isdigit():
                            segments.append(V11Seg.face(int(face_id)))
                        else:
                            segments.append(V11Seg.image(file=f"FOUND://{face_id}"))
                elif name:
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
