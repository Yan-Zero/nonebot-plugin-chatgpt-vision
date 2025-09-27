from typing import Optional
from nonebot import get_plugin_config
from pydantic import BaseModel


class Config(BaseModel):
    # 默认与回退模型
    fallback_model: str = "gemini-2.5-flash"
    """ 回退模型，一个用户达到限额或默认模型不可用时调用 """

    # 拟人聊天
    chat_mode: bool = False
    chat_max_log: int = 60
    chat_group: list[str] = []
    # 是否去除每句话末尾的句号
    chat_remove_period: bool = True

    # 图片与识别
    image_mode: int = 1

    # MCP（Model Context Protocol）
    mcp_enabled: bool = False
    """ 是否启用 MCP 工具装载 """
    mcp_config_file: str = "configs/chatgpt-vision/mcp.yaml"
    """ YAML 文件路径，支持同时配置多个 stdio/SSE MCP 源 """

    tool_proxy_url: Optional[str] = None
    """ 工具代理服务器地址，若为空则不使用代理 """

    # Markdown 渲染
    markdown_server: str = ""
    """ Markdown 渲染服务器，若为空则不渲染 """


p_config: Config = get_plugin_config(Config)
