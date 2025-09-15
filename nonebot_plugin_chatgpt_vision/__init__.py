from nonebot.plugin import PluginMetadata

# 移除对 mcp[cli] 的强制导入检查，允许仅 HTTP 模式运行

from .config import Config
from .human_like import GROUP_RECORD

__plugin_meta__ = PluginMetadata(
    name="ChatGPT",
    description="",
    usage="",
    config=Config,
)
