from nonebot.plugin import PluginMetadata

try:
    from mcp.client.session import ClientSession  # type: ignore  # noqa: F401
    from mcp.client.stdio import stdio_client  # type: ignore  # noqa: F401
except Exception as e:  # pragma: no cover - 明确提示安装 mcp[cli]
    raise RuntimeError(
        "未检测到 mcp[cli] 运行时，请先安装依赖：`pip install mcp[cli]` 或在 Poetry 中声明 mcp = {extras=['cli'], version='^1.14.0'}"
    ) from e


from .config import Config
from .human_like import RecordSeg

__plugin_meta__ = PluginMetadata(
    name="ChatGPT",
    description="",
    usage="",
    config=Config,
)
