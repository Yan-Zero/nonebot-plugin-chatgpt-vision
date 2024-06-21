import hashlib
import re
import pypandoc
from PIL import Image
from io import BytesIO
from datetime import datetime
from tex2img import AsyncLatex2PNG
from nonebot import get_plugin_config
from nonebot import on_command
from nonebot.adapters import Event
from nonebot.adapters import Bot
from nonebot.adapters import Message
from nonebot.plugin import PluginMetadata
from nonebot.params import CommandArg
from nonebot.adapters.onebot.v11.message import Message as V11M

from nonebot.adapters.onebot.v11.message import MessageSegment as V11Seg
from nonebot.adapters.onebot.v11.event import GroupMessageEvent as V11GME
from nonebot.permission import SUPERUSER

from .config import Config
from .chat import chat
from .chat import error_chat
from .fee.userrd import UserRD
from .human_like import RecordSeg
from .picsql import upload_image
from .plugin.chat import reset

__plugin_meta__ = PluginMetadata(
    name="ChatGPT",
    description="",
    usage="",
    config=Config,
)
