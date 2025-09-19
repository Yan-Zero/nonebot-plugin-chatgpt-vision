from nonebot import get_plugin_config
from pydantic import BaseModel


class Config(BaseModel):
    """Plugin Config Here"""

    # 默认与回退模型
    openai_default_model: str = "gpt-4o"
    """ 默认模型 """
    fallback_model: str = "gemini-2.5-flash"
    """ 回退模型，一个用户达到限额或默认模型不可用时调用 """

    # 额度相关
    limit_for_single_user: float = 0.05
    """ 单个用户限额花费，单位是美元 """
    max_token_per_user: int = 300
    """ 单条最大回复 tokens """
    max_chatlog_count: int = 15
    """ 历史记录最大长度（包括 GPT） """
    max_history_tokens: int = 3000
    """ 历史记录最大 tokens（只包括 User） """

    # 拟人聊天
    human_like_chat: bool = False
    human_like_max_tokens: int = 6000
    human_like_max_log: int = 60
    human_like_group: list[str] = []

    # SD 绘图
    sd_url: str = (
        "https://api.siliconflow.cn/v1/stabilityai/stable-diffusion-xl-base-1.0/"
    )
    sd_key: str = ""

    # 图片与识别
    image_mode: int = 1
    image_classification_url: str = ""
    image_classification_id: str = ""

    image_cdn_url: str = ""
    image_cdn_key: str = ""
    image_cdn_put_url: str = ""

    chat_with_image: bool = False

    # MCP（Model Context Protocol）
    mcp_enabled: bool = False
    """ 是否启用 MCP 工具装载 """

    # 额外：集中 YAML 配置多个 MCP 源
    mcp_config_file: str = "configs/chatgpt-vision/mcp.yaml"
    """ YAML 文件路径，支持同时配置多个 stdio/SSE MCP 源 """

    markdown_server: str = ""
    """ Markdown 渲染服务器，若为空则不渲染 """


p_config: Config = get_plugin_config(Config)
