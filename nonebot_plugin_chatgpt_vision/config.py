from pydantic import BaseModel
from sqlalchemy import TEXT
from sqlalchemy import BOOLEAN
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.ext.declarative import declarative_base

Model = declarative_base(name="Model")


class Config(BaseModel):
    """Plugin Config Here"""

    openai_default_model: str = "gpt-4o"
    """ 默认模型 """
    fallback_model: str = "gpt-3.5-turbo"
    """ 回退模型，一个用户达到限额后调用 """
    limit_for_single_user: float = 0.05
    """ 单个用户限额花费，单位是美元 """
    max_token_per_user: int = 300
    """ 单条最大回复 tokens """
    max_chatlog_count: int = 15
    """ 历史记录最大长度（包括 GPT） """
    max_history_tokens: int = 3000
    """ 历史记录最大 tokens（只包括 User） """

    dashscope_embedding_apikey: str = ""
    dashscope_embedding_baseurl: str = ""

    human_like_chat: bool = False
    human_like_max_tokens: int = 6000
    human_like_max_log: int = 60
    human_like_group: list[str] = []

    sd_url: str = (
        "https://api.siliconflow.cn/v1/stabilityai/stable-diffusion-xl-base-1.0/"
    )
    sd_key: str = ""

    savepic_sqlurl: str
    embedding_sqlurl: str
    dashscope_api: str
    notfound_with_jpg: bool = True

    image_mode: int = 1
    image_classification_url: str = ""
    image_classification_id: str = ""

    image_cdn_url: str = ""
    image_cdn_key: str = ""
    image_cdn_put_url: str = ""

    chat_with_image: bool = False


class PicData(Model):
    """消息记录"""

    __tablename__ = "picdata"

    __table_args__ = {"extend_existing": True}

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(TEXT)
    """ 图片名称 """
    group: Mapped[str] = mapped_column(TEXT)
    """ 所属群组 id """
    url: Mapped[str] = mapped_column(TEXT)
    """ 图片目录 """
    u_vec_img: Mapped[bool] = mapped_column(BOOLEAN, nullable=False, default=False)
    u_vec_text: Mapped[bool] = mapped_column(BOOLEAN, nullable=False, default=False)
