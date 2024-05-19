from pydantic import BaseModel


class Config(BaseModel):
    """Plugin Config Here"""

    openai_default_model: str = "gpt-4o"
    """ 默认模型 """
    fallback_model: str = "gpt-3.5-turbo"
    """ 回退模型，一个用户达到限额后调用 """
    limit_for_single_user: int = 0.1
    """ 单个用户限额花费，单位是美元 """
    max_token_per_user: int = 300
    """ 单条最大回复 tokens """
    max_chatlog_count: int = 15
    """ 历史记录最大长度（包括 GPT） """
    max_history_tokens: int = 3000
    """ 历史记录最大 tokens（只包括 User） """

    openai_pool_model_config: list[str] = []
    openai_pool_key_config: list[str] = []
    openai_pool_baseurl_config: list[str] = []

    dashscope_embedding_apikey: str = ""
    dashscope_embedding_baseurl: str = ""

    human_like_chat: bool = False
    human_like_max_tokens: int = 6000
    human_like_max_log: int = 30
    human_like_group: list[str] = []
