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

    oepnai_pool_config: list = []
    """ 格式是 [
        [model, key, baseurl],
        ...
    ]，例如：[
        ["gpt-4o", "sk-***", "https://api.openai/v1"],
        ["gpt-4o", "sk-***", "ditto"],
        ...
    ]，其中，ditto 会被处理成与上个的 baseurl 相同 """
