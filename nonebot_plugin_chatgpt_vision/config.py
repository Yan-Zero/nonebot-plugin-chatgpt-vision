from nonebot import get_plugin_config
from pydantic import BaseModel


class Config(BaseModel):
    """Plugin Config Here"""

    # 默认与回退模型
    openai_default_model: str = "gpt-4o"
    """ 默认模型 """
    fallback_model: str = "gemini-2.5-flash"
    """ 回退模型，一个用户达到限额或默认模型不可用时调用 """

    # 拟人聊天
    chat_mode: bool = False
    chat_max_log: int = 60
    chat_group: list[str] = []

    # 图片与识别
    image_mode: int = 1
    # image_cdn_url: str = ""
    # image_cdn_key: str = ""
    # image_cdn_put_url: str = ""

    # MCP（Model Context Protocol）
    mcp_enabled: bool = False
    """ 是否启用 MCP 工具装载 """
    mcp_config_file: str = "configs/chatgpt-vision/mcp.yaml"
    """ YAML 文件路径，支持同时配置多个 stdio/SSE MCP 源 """

    markdown_server: str = ""
    """ Markdown 渲染服务器，若为空则不渲染 """


p_config: Config = get_plugin_config(Config)
