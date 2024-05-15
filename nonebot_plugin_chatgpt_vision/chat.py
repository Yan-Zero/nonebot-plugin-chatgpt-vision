from nonebot import get_plugin_config

from openai import APIError
from openai import RateLimitError

from .pool import OpenAI_Pool
from .pool import OpenAI_Config
from .config import Config


config: Config = get_plugin_config(Config)

list_for_config: list[OpenAI_Config] = []
for i in range(len(config.openai_pool_model_config)):
    model = config.openai_pool_model_config[i]
    key = config.openai_pool_key_config[i]
    url = config.openai_pool_baseurl_config[i]
    if url == "ditto":
        url = list_for_config[-1].baseurl
    if model == "ditto":
        model = list_for_config[-1].model
    list_for_config.append(OpenAI_Config(baseurl=url, apikey=key, model=model))

POOL = OpenAI_Pool(config=list_for_config)


async def chat(message: list, model: str, times: int = 3) -> dict:
    for _ in range(times - 1):
        cilent = POOL(model=model)
        try:
            return (
                await cilent.chat.completions.create(messages=message, model=model)
            ).dict()
        except RateLimitError:
            POOL.RequestLimit(model=model, cilent=cilent, timeout=120)
    return (
        await POOL(model=model).chat.completions.create(messages=message, model=model)
    ).dict()
