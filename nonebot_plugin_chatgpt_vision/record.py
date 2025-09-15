import io
import base64
import aiohttp

from PIL import Image
from typing import Any, Optional
from datetime import datetime
from nonebot.adapters.onebot.v11.message import Message as V11Msg
from nonebot.adapters.onebot.v11.message import MessageSegment as V11Seg

from .utils import USER_NAME_CACHE, QFACE
from .picsql import resnet_50, upload_image


async def seg2text(seg: V11Seg, chat_with_image: bool = False):
    if seg.is_text():
        return seg.data["text"] or ""
    if seg.type == "at":
        if seg.data["qq"] in USER_NAME_CACHE:
            name = USER_NAME_CACHE[seg.data["qq"]]
        elif "name" in seg.data:
            name = seg.data["name"]
            if not name or not name.strip():
                name = str(seg.data["qq"])[:5]
            USER_NAME_CACHE[seg.data["qq"]] = name
        else:
            name = str(seg.data["qq"])[:5]
        return f"@{name}({seg.data['qq']}) "
    if seg.type == "face":
        return f"[image,{QFACE.get(seg.data['id'], 'notfound')}]"
    if seg.type == "image":
        if chat_with_image:
            return ""
        return f"[image,{await resnet_50(seg.data['file'])}]"
    if seg.type == "mface":
        if chat_with_image:
            return ""
        return f"[image,{seg.data['summary'][1:-1]}]"
    if seg.type == "record":
        return "[record]"
    return f"[{seg.type}]"


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


class RecordSeg:
    name: str
    uid: str
    msg: V11Msg
    time: datetime
    msg_id: int

    reply: Optional["RecordSeg"]
    images: list[str]

    def __init__(
        self,
        name: str,
        uid: str,
        msg: V11Msg | str,
        msg_id: int,
        time: datetime,
        images: list[str] = [],
        reply: Optional["RecordSeg"] = None,
    ):
        self.name = name
        self.uid = uid
        if isinstance(msg, str):
            msg = V11Msg(msg)
        self.msg = msg
        self.time = time
        self.msg_id = msg_id
        if images:
            self.images = images
        else:
            self.images = []
        self.reply = reply

    def __str__(self):
        return self.to_str(with_title=True)

    def to_str(self, with_title: bool = False):
        ret = ""
        if with_title:
            ret += f"{self.name}({self.uid})[{self.time.strftime('%Y-%m-%d %H:%M %a')}]：\n"
        if self.reply:
            ret += f"Reply to @{self.reply.name}({self.reply.uid})：\n"
            ret += "\n> ".join(self.reply.to_str().split("\n")) + "\n"
        return ret + self.msg.extract_plain_text()

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

        temp = V11Msg()
        for seg in self.msg:
            if seg.type == "image":
                url = seg.data["file"]
                # 处理GIF转PNG
                url = await convert_gif_to_png_base64(url)
                # 如果不是base64格式，继续原来的上传逻辑
                if not url.startswith("data:"):
                    url = await upload_image(url)
                seg.data["file"] = url
                self.images.append(url)

            if seg.type == "mface":
                url = seg.data["url"]
                # 处理GIF转PNG
                url = await convert_gif_to_png_base64(url)
                # 如果不是base64格式，继续原来的上传逻辑
                if not url.startswith("data:"):
                    url = await upload_image(url)
                seg.data["url"] = url
                self.images.append(url)

            temp.append(await seg2text(seg, image_mode))
        self.msg = temp
