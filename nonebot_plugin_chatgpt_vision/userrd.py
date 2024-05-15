from nonebot import get_plugin_config
from datetime import datetime
from datetime import timedelta

from .config import Config

p_config: Config = get_plugin_config(Config)


def get_comsumption(usage: dict, model: str) -> float:
    pt = usage["prompt_tokens"]
    ct = usage["completion_tokens"]

    if model.startswith("gpt-3.5"):
        return (0.5 * pt + 1.5 * ct) / 1_000_000
    if model.startswith("gpt-4o"):
        return (5 * pt + 15 * ct) / 1_000_000
    if model.startswith("gpt-4-"):
        return (30 * pt + 60 * ct) / 1_000_000

    return (10 * pt + 30 * ct) / 1_000_000
    # 乱算的，能用就行了


class UserRD:
    chatlog: list
    model: str
    consumption: float
    time: datetime
    count: int

    def __init__(self) -> None:
        self.chatlog = []
        self.time = datetime.now()
        self.consumption = 0
        self.model = p_config.openai_default_model
        self.count = 0

    def check(self) -> bool:
        if self.consumption < p_config.limit_for_single_user:
            return False
        if datetime.now() - self.time > timedelta(days=1):
            self.time = datetime.now()
            self.consumption = 0
            return False
        return True

    def image(self, count: int = 1):
        if self.model.startswith("gpt-4o"):
            self.consumption += 0.003825 * count
        else:
            self.consumption += 0.00765 * count

    def append(self, response) -> bool:
        if "prompt_tokens" in response:
            pt = response["prompt_tokens"]
        else:
            pt = 100

        self.consumption += get_comsumption(response["usage"], response["model"])
        self.count += 1
        self.chatlog.append(response["choices"][0]["message"])

        if pt > p_config.max_history_tokens or self.count >= p_config.max_chatlog_count:
            self.chatlog.pop(0)
            self.model = p_config.fallback_model
            return True
        return False
