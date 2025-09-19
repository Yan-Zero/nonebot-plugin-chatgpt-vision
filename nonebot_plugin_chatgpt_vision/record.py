import yaml
import bisect

from lxml import etree  # type: ignore
from collections.abc import Iterable
from typing import Any, Optional
from datetime import datetime
from nonebot.adapters.onebot.v11.message import Message as V11Msg
from nonebot.adapters.onebot.v11.message import MessageSegment as V11Seg

from .utils import QFACE, convert_gif_to_png_base64
from .picsql import upload_image


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
            _append_text(p, data.get("text", "").replace("\n", "<br/>"))

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
            # <face name="..." id="..."/>
            face_id = data.get("id")
            name = QFACE.get(face_id, f"表情{face_id}")
            face = etree.SubElement(p, "face")
            face.set("name", name)
            face.set("id", face_id)

        elif st == "image":
            # <image name="..."/> 或 <image url="..."/>
            file_ = data.get("file")
            image = etree.SubElement(p, "image")
            if file_:
                url = await convert_gif_to_png_base64(file_)
                file_ = await upload_image(url)
                image.set("url", file_)
                images.append(file_)

        elif st == "mface":
            image = etree.SubElement(p, "image")
            file_ = data.get("url")
            if file_:
                image.set("url", file_)
                url = await convert_gif_to_png_base64(file_)
                images.append(await upload_image(url))

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
            if summary_inner:
                image.set("name", summary_inner)

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
        if reply and reply.images:
            self.images = reply.images + self.images

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

    def recall(
        self,
        msg_id: str | int,
        user_id: str | None = None,
        delete_time: datetime | None = None,
    ) -> bool:
        if not delete_time:
            delete_time = datetime.now()
        for record in self.records:
            if user_id and record.uid != user_id:
                continue
            for j, (mid, _) in enumerate(record.msg):
                if mid == str(msg_id):
                    record.msg[j] = (
                        mid,
                        f"<p>[DELETE at {delete_time.strftime('%Y-%m-%d %H:%M %a')}]</p>",
                    )
                    return True
        return False

    def message(self, bot_uid: str, image_mode: bool = False) -> list[dict]:
        ret = []
        for record in self.records:
            if record.uid == bot_uid:
                data: dict[str, Any] = {
                    "role": "assistant",
                }
                for id, value in record.msg:
                    if id == "content":
                        data[id] = value
                    else:
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


XML_PROMPT = (
    """Here is a message in XML format. The message may contain text, mentions, replies, and images.
<p> tags represent paragraphs of text. 这里的段指的是给用户显示的不同信息段，而不是以换行符分割的段落。
<br/> tags represent line breaks within a paragraph. but you can also use "\\n" to represent line breaks.
<mention> tags represent mentions of users, with an "uid" attribute for the user ID and the text content being the user's name.
<reply> tags represent replies to other messages, with an "id" attribute for the message ID being replied to。一个p tag内只能有一个reply标签。
<image> tags represent images, with a "name" attribute for the image name. 如果你想发的是互联网上的照片，则请设定 url 属性，属性值为图片的 URL，例如<image url="https://q1.qlogo.cn/g?b=qq&nk=114514&s=640"/>。
<face> 标签代表QQ内置表情，具有 name 和 id 属性，例如 <face name="斜眼笑" id="178"/>。
<code> 标签代表代码块，具有一个可选的 lang 属性表示代码语言，例如 <code lang="python">print("Hello, World!")</code>。如果没有指定 lang 属性，则表示普通文本代码块。
建议使用CDATA来包裹代码内容以避免转义问题，例如 <code lang="python"><![CDATA[print("Hello, World!")]]></code>。lang 为 markdown 时，代码块会被渲染成图片，因此适合用来展示复杂的数学公式。
<tex> 标签代表行内公式，例如 <tex>E=mc^2</tex>。

除了上面提到的标签，你不应该使用其他标签，例如<ol>、<li>、<b>、<i>等标签，因为这不是 HTML 或者完全的 XML。

你的回复应该类似于：
<p><reply id="-1696903780"/>这是真的吗？<mention uid="114514"/></p>
<p><image name="笑"/></p>
<p>这是一个段落。<br/>这是同一段内的换行。</p>
<p>根据爱因斯坦质能方程<tex>E=mc^2</tex>，我觉得静质量 m 和能量 E 之间的关系非常有趣。</p>

通常意义下，如果公式和文字反复穿插，**必须**使用 <code lang="markdown"> 来表示。
"""
    r"""
WARNING: 你只能使用上面提到的标签，不能使用其他标签，否则会导致 XML 解析失败。
WARNING: 你必须正确转义 XML 相关的符号，特别是 & < > " ' 等符号，否则会导致 XML 解析失败。
WARNING: 如果你的回答有数学公式，建议直接使用多行公式 <code lang="markdown"> 回答答案，包括文字部分。除非你能完全确保公式只有几个字符，否则不要使用 <tex> 标签。

换而言之 <code lang="markdown"> 的优先级远远大于**一堆 p tags 和 tex tags**的混用。这是一个标准的多行数学问题回答实践：
```
<p><reply id="-1696903780"/>本喵知道了喵！坏b主人，做题就做题嘛，为什么凶咱</p>

<p><code lang="typst"><![CDATA[
要证明函数图像关于 y = x 对称，只需证明将原方程中的 x 和 y 互换后，得到的方程与原方程等价。  

原方程为：

#math(display: sin(x - y) + 4 * sin(y) = 4 * sin(x + y))

将 x 和 y 互换，得到：

#math(display: sin(y - x) + 4 * sin(x) = 4 * sin(x + y))

利用三角函数性质 #math(sin(y - x) = -sin(x - y)) 和 #math(sin(y + x) = sin(x + y))，上式可化为：

#math(display: -sin(x - y) + 4 * sin(x) = 4 * sin(x + y)) \ (*)
]]></code></p>

<p><code lang="typst"><![CDATA[
= 对原方程进行恒等变形

#align(
  sin(x - y) &= 4 * sin(x + y) - 4 * sin(y) \
  sin(x) * cos(y) - cos(x) * sin(y) &= 4 * (sin(x)*cos(y)+cos(x)*sin(y)) - 4*sin(y) \
  3*sin(x)*cos(y) + 5*cos(x)*sin(y) - 4*sin(y) &= 0 \
  3*sin(x)*cos(y) + (5*cos(x)-4)*sin(y) &= 0 \ (#)
)
]]></code></p>

<p><code lang="typst"><![CDATA[
= 对变换后的方程 (*) 进行恒等变形

#align(
  4*sin(x) &= 4*sin(x+y) + sin(x-y) \
  4*sin(x) &= 4*(sin(x)*cos(y)+cos(x)*sin(y)) + (sin(x)*cos(y)-cos(x)*sin(y)) \
  4*sin(x) &= 5*sin(x)*cos(y) + 3*cos(x)*sin(y) \
  (4 - 5*cos(y))*sin(x) - 3*cos(x)*sin(y) = 0 \ (##)
)
]]></code></p>

<p><code lang="typst"><![CDATA[
= 证明 (#) 与 (##) 等价

#align(
  3*sin(x)*cos(y) &= -(5*cos(x)-4)*sin(y) \
  (4-5*cos(y))*sin(x) &= 3*cos(x)*sin(y) \
  3*sin(x)^2*cos(y)*(4-5*cos(y)) &= -3*cos(x)*sin(y)^2*(5*cos(x)-4) \
  sin(x)^2*(4*cos(y)-5*cos(y)^2) &= -cos(x)*sin(y)^2*(5*cos(x)-4) \
  (1-cos(x)^2)*(4*cos(y)-5*cos(y)^2) &= -cos(x)*(1-cos(y)^2)*(5*cos(x)-4)
)

展开整理后，两边都等于：

#align(
  4*cos(y) - 5*cos(y)^2 - 4*cos(x)^2*cos(y) + 5*cos(x)^2*cos(y)^2 \
  = -5*cos(x)^2 + 4*cos(x) + 5*cos(x)^2*cos(y)^2 - 4*cos(x)*cos(y)^2
)
]]></code></p>

<p>由于此恒等式成立，说明方程 (#) 和 (##) 是等价的  
因此，原方程与交换 x, y 后的方程是等价的  
所以，该图像在 <code lang="typst">#math(x ∈ (0, π), y ∈ (0, π))</code> 上关于直线 y=x 对称</p>

<p>QED 喵~</p>
```

"""
)


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
                # <mention uid="...">可选 name</mention>
                uid = int(sub.get("uid", "10001"))
                segments.append(V11Seg.at(uid))
                if sub.tail:
                    segments.append(V11Seg.text(sub.tail))
            elif sub.tag == "reply":
                # <reply id="..."/>
                mid = int(sub.get("id", "0"))
                segments.append(V11Seg.reply(mid))
                if sub.text:
                    segments.append(V11Seg.text(sub.text))
                if sub.tail:
                    segments.append(V11Seg.text(sub.tail))
            elif sub.tag == "image":
                # <image name="..." url="..."/>
                name = sub.get("name", None)
                url = sub.get("url", None)
                if url and url.startswith("http"):
                    segments.append(V11Seg.image(file=url))
                elif name:
                    segments.append(V11Seg.image(file=f"FOUND://{name}"))
                if sub.tail:
                    segments.append(V11Seg.text(sub.tail))
            elif sub.tag in {"time", "name", "uid"}:
                # 标签本身忽略，仅拼接其后续文本
                if sub.tail:
                    segments.append(V11Seg.text(sub.tail))
            elif sub.tag == "face":
                # <face name="..." id="..."/>
                face_id = sub.get("id", "0")
                segments.append(V11Seg.face(face_id))
                if sub.tail:
                    segments.append(V11Seg.text(sub.tail))
            elif sub.tag == "code":
                # <code lang="...">...</code>
                lang = sub.get("lang", "text")
                code = sub.text or ""
                if lang.lower() == "typst":
                    segments.append(V11Seg.image(file=f"TYPST://{code}"))
                else:
                    segments.append(V11Seg.text(f"```{lang}\n{code}\n```"))
            elif sub.tag == "tex":
                # <tex>...</tex>
                code = sub.text or ""
                if code.strip():
                    segments.append(V11Seg.image(file=f"MATH://{code.strip()}"))
                if sub.tail:
                    segments.append(V11Seg.text(sub.tail))
            elif sub.tag == "br":
                segments.append(V11Seg.text("\n"))
                if sub.tail:
                    segments.append(V11Seg.text(sub.tail))
            else:
                # 未知子标签整体当作文本
                segments.append(V11Seg.text(etree.tostring(sub, encoding="unicode")))
                if sub.tail:
                    segments.append(V11Seg.text(sub.tail))
        if len(segments) == 1 and segments[0].type == "reply":
            # 仅有 reply 标签，补一个句号，避免空消息
            segments.append(V11Seg.text("。"))
        return segments

    ps = list(root.iter("p"))
    if ps:
        for p in ps:
            segs = _segments_from_p(p)
            # 避免产出空消息
            if segs:
                yield V11Msg(segs)
        return

    raise ValueError("No <p> tags found in XML input.")
