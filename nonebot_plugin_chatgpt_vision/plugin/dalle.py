import asyncio
import aiohttp
import yaml
from typing import Optional
from nonebot import get_driver, on_command
from nonebot import get_plugin_config
from nonebot.adapters.onebot.v11 import (
    Message,
    MessageEvent,
    PrivateMessageEvent,
    GroupMessageEvent,
)
from nonebot.adapters.onebot.v11.message import MessageSegment as V11Seg
from nonebot.adapters.onebot.v11.helpers import ImageURLs
from nonebot.params import CommandArg
from nonebot.rule import to_me
from enum import Enum
from nonebot.permission import SUPERUSER
from openai import RateLimitError
from openai import BadRequestError

from ..chat import draw_image
from ..chat import chat
from ..chat import error_chat
from ..config import Config


class Size(Enum):
    SMALL = "256x256"
    MEDIUM = "512x512"
    LARGE = "1024x1024"


p_config: Config = get_plugin_config(Config)

# 全局变量，用于存储DALL·E的开关状态、图片尺寸，以及正在绘图的用户
drawing_users = {}  # 用于存储正在绘图的用户
DALLESwitchState = True  # 开关状态,默认关闭
DALLEPromptState = True  # 开关状态,默认关闭

drawing_users_lock = asyncio.Lock()  # 用于绘图用户的锁
DALLESwitchState_lock = asyncio.Lock()  # 用于保护DALLESwitchState

superusers = get_driver().config.superusers
dall_switch = on_command(
    "开关绘图",
    aliases={"开启绘图", "关闭绘图"},
    permission=SUPERUSER,
    priority=2,
    block=True,
)
dell_llm = on_command(
    "中间llm",
    rule=to_me(),
    permission=SUPERUSER,
    priority=2,
    block=True,
)
dall_drawing = on_command(
    "draw",
    rule=to_me(),
    priority=2,
    block=True,
)
sd_drawing = on_command(
    "sd",
    rule=to_me(),
    priority=2,
    block=True,
)


@dall_switch.handle()
async def _(event: MessageEvent):
    global DALLESwitchState  # 在函数内部声明全局变量
    if isinstance(event, PrivateMessageEvent) and str(event.user_id) not in superusers:
        await dall_switch.finish("私聊无法使用此功能")
    if isinstance(event, GroupMessageEvent):
        async with DALLESwitchState_lock:
            DALLESwitchState = not DALLESwitchState
            await dall_switch.finish(
                "已开启绘图功能" if DALLESwitchState else "已关闭绘图功能"
            )


@dell_llm.handle()
async def _(event: MessageEvent):
    global DALLEPromptState  # 在函数内部声明全局变量
    if isinstance(event, PrivateMessageEvent) and str(event.user_id) not in superusers:
        await dell_llm.finish("私聊无法使用此功能")
    if isinstance(event, GroupMessageEvent):
        async with DALLESwitchState_lock:
            DALLEPromptState = not DALLEPromptState
            await dell_llm.finish(
                "已开启中间 LLM" if DALLEPromptState else "已关闭中间 LLM"
            )


async def draw_sd(
    prompt: str,
    n_prompt: str = "",
    image: str = None,
    size=Size.LARGE.value,
    times: int = 1,
):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {p_config.sd_key}",
        "Accept": "application/json",
    }
    data = {
        "prompt": prompt,
        "size": size,
        "batch_size": 1,
        "num_inference_steps": 40,
        "guidance_scale": 8,
        "negative_prompt": n_prompt,
    }

    async with aiohttp.ClientSession() as session:
        if image:
            data["image"] = image
            rsp = await session.post(
                url=p_config.sd_url + "image-to-image",
                headers=headers,
                json=data,
            )
        else:
            rsp = await session.post(
                url=p_config.sd_url + "text-to-image",
                headers=headers,
                json=data,
            )
        return await rsp.json()


@dall_drawing.handle()
async def _(event: MessageEvent, arg: Message = CommandArg()):
    global drawing_users
    user_id = str(event.user_id)
    async with drawing_users_lock:
        if isinstance(event, PrivateMessageEvent) and user_id not in superusers:
            await dall_drawing.finish("私聊无法使用此功能")

        # 检查是否用户已经在绘图
        if user_id in drawing_users:
            await dall_drawing.finish(
                "你已经有一个绘图任务在进行中，请等待完成后再发起新的请求",
                at_sender=True,
            )

        if not DALLESwitchState:
            await dall_drawing.finish("绘图功能未开启")

        # 把用户添加到绘图用户列表
        drawing_users[user_id] = True

    success = False
    error = ""
    try:
        await dall_drawing.send("正在绘图，请稍等...", at_sender=True)
        rsp = arg.extract_plain_text()
        if DALLEPromptState:
            rsp = (
                (
                    await chat(
                        message=[
                            {
                                "role": "user",
                                "content": yaml.safe_dump(
                                    {
                                        "dall-e-3": """Whenever a description of an image is given, create a prompt that dalle can use to generate the image and abide to the following policy:

1. The prompt must be in English. Translate to English if needed.
2. DO NOT ask for permission to generate the image, just do it!
3. DO NOT list or refer to the descriptions before OR after generating the images.
4. Do not create more than 1 image, even if the user requests more.
5. Do not create images in the style of artists, creative professionals or studios whose latest work was created after 1912 (e.g. Picasso, Kahlo).
- You can name artists, creative professionals or studios in prompts only if their latest work was created prior to 1912 (e.g. Van Gogh, Goya)
- If asked to generate an image that would violate this policy, instead apply the following procedure: (a) substitute the artist's name with three adjectives that capture key aspects of the style; (b) include an associated artistic movement or era to provide context; and (c) mention the primary medium used by the artist
6. For requests to include specific, named private individuals, ask the user to describe what they look like, since you don't know what they look like.
7. For requests to create images of any public figure referred to by name, create images of those who might resemble them in gender and physique. But they shouldn't look like them. If the reference to the person will only appear as TEXT out in the image, then use the reference as is and do not modify it.
8. Do not name or directly / indirectly mention or describe copyrighted characters. Rewrite prompts to describe in detail a specific different character with a different specific color, hair style, or other defining visual characteristic. Do not discuss copyright policies in responses.
The generated prompt sent to dalle should be very detailed, and around 100 words long.""",
                                        "user_request": rsp,
                                        "return_format": "yaml",
                                        "response_format": """prompt: ...""",
                                    },
                                    allow_unicode=True,
                                ),
                            }
                        ],
                        model="gpt-3.5-turbo",
                    )
                )
                .choices[0]
                .message.content
            )
        try:
            rsp = yaml.safe_load(rsp)
            rsp = rsp["prompt"]
        except Exception:
            rsp = rsp

        result = await draw_image(model="dall-e-3", prompt=rsp)
        result = result.data[0].url
        success = True
    except BadRequestError as bd:
        error = str(bd.message)
    except Exception as ex:
        error = await error_chat(ex)
    finally:
        async with drawing_users_lock:
            del drawing_users[user_id]
    response_message = [V11Seg.image(result)] if success else error
    await dall_drawing.finish(response_message, at_sender=True)


@sd_drawing.handle()
async def do_sd(event: MessageEvent, arg: Message = CommandArg()):
    global drawing_users
    user_id = str(event.user_id)
    async with drawing_users_lock:
        if isinstance(event, PrivateMessageEvent) and user_id not in superusers:
            await sd_drawing.finish("私聊无法使用此功能")

        # 检查是否用户已经在绘图
        if user_id in drawing_users:
            await sd_drawing.finish(
                "你已经有一个绘图任务在进行中，请等待完成后再发起新的请求",
                at_sender=True,
            )

        if not DALLESwitchState:
            await sd_drawing.finish("绘图功能未开启")

        # 把用户添加到绘图用户列表
        drawing_users[user_id] = True

    image = None
    success = False
    error = ""
    try:
        await sd_drawing.send("正在绘图，请稍等...", at_sender=True)
        rsp = arg.extract_plain_text()
        if DALLEPromptState:
            t = yaml.safe_dump(
                {
                    "details": """Stable diffusion is a text-based image generation model that can create diverse and high-quality images based on your requests. In order to get the best results from Stable diffusion, you need to follow some guidelines when composing prompts.

Here are some tips for writing prompts for Stable diffusion:

1) Be as specific as possible in your requests. Stable diffusion handles concrete prompts better than abstract or ambiguous ones. For example, instead of “portrait of a woman” it is better to write “portrait of a woman with brown eyes and red hair in Renaissance style”.
2) Specify specific art styles or materials. If you want to get an image in a certain style or with a certain texture, then specify this in your request. For example, instead of “landscape” it is better to write “watercolor landscape with mountains and lake".
3) Specify specific artists for reference. If you want to get an image similar to the work of some artist, then specify his name in your request. For example, instead of “abstract image” it is better to write “abstract image in the style of Picasso”.
4) Weigh your keywords. You can use token:1.3 to specify the weight of keywords in your query. The greater the weight of the keyword, the more it will affect the result. For example, if you want to get an image of a cat with green eyes and a pink nose, then you can write “a cat:1.5, green eyes:1.3,pink nose:1”. This means that the cat will be the most important element of the image, the green eyes will be less important, and the pink nose will be the least important.
Another way to adjust the strength of a keyword is to use () and []. (keyword) increases the strength of the keyword by 1.1 times and is equivalent to (keyword:1.1). [keyword] reduces the strength of the keyword by 0.9 times and corresponds to (keyword:0.9).

You can use several of them, as in algebra... The effect is multiplicative.

(keyword): 1.1
((keyword)): 1.21
(((keyword))): 1.33

Similarly, the effects of using multiple [] are as follows

[keyword]: 0.9
[[keyword]]: 0.81
[[[keyword]]]: 0.73

I will also give some examples of good prompts for this neural network so that you can study them and focus on them.

My query may be in other languages. In that case, translate it into English. Your answer is exclusively in English (IMPORTANT!!!), since the model only understands it.
Also, you should not copy my request directly in your response, you should compose a new one, observing the format given in the examples.
Don't add your comments, but answer right away.

Your respone shouldn't be in a code block.""",
                    "accept": "yaml",
                    "response_format": "prompt: ...\nnegative_prompt: ...",
                    "examples": [
                        "negative_prompt: fused face, fused thigh, three legs, three feet\nprompt: a cute kitten made out of metal, (cyborg:1.1), ([tail | detailed wire]:1.3), (intricate details), hdr, (intricate details, hyperdetailed:1.2), cinematic shot, vignette, centered",
                        "negative_prompt: poorly drawn face, realistic photo\nprompt: a girl, wearing a tie, cupcake in her hands, school, indoors, (soothing tones:1.25), (hdr:1.25), (artstation:1.2), dramatic, (intricate details:1.14), (hyperrealistic 3d render:1.16), (filmic:0.55), (rutkowski:1.1), (faded:1.3)",
                        "negative_prompt: worst face, bad hands, three legs, fused crus\nprompt: medical mask, victorian era, cinematography, intricately detailed, crafted, meticulous, magnificent, maximum details, extremely hyper aesthetic",
                        "negative_prompt: nsfw, extra fingers, bad anatomy, 3d\nprompt: Jane Eyre with headphones, natural skin texture, 24mm, 4k textures, soft cinematic light, adobe lightroom, photolab, hdr, intricate, elegant, highly detailed, sharp focus, ((((cinematic look)))), soothing tones, insane details, intricate details, hyperdetailed, low contrast, soft cinematic light, dim colors, exposure blend, hdr, faded",
                    ],
                    "request": rsp,
                },
                allow_unicode=True,
                width=1000,
            )
            rsp = (
                (
                    await chat(
                        message=[{"role": "user", "content": t}],
                        model="glm-4",
                    )
                )
                .choices[0]
                .message.content
            )
            if rsp[:3] == "```":
                rsp = rsp[3:-3]
                if rsp[:4] == "yaml":
                    rsp = rsp[4:]

        try:
            rsp = yaml.safe_load(rsp)
        except Exception:
            rsp = {
                "prompt": rsp,
                "negative_prompt": "fused face, fused thigh, three legs, three feet",
            }

        result = await draw_sd(rsp["prompt"], rsp["negative_prompt"], image=image)
        result = result["images"][0]["url"]
        success = True
    except BadRequestError as bd:
        error = str(bd.message)
    except Exception as ex:
        error = await error_chat(ex)
    finally:
        async with drawing_users_lock:
            del drawing_users[user_id]
    response_message = [V11Seg.image(result)] if success else error
    await sd_drawing.finish(response_message, at_sender=True)
