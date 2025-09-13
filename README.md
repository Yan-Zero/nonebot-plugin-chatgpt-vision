# nonebot-plugin-chatgpt-vision

[![NoneBotPluginLogo](https://github.com/A-kirami/nonebot-plugin-chatgpt-vision/blob/resources/nbp_logo.png)](https://v2.nonebot.dev/store)

[![license](https://img.shields.io/github/license/owner/nonebot-plugin-chatgpt-vision.svg)](./LICENSE)
[![pypi](https://img.shields.io/pypi/v/nonebot-plugin-chatgpt-vision.svg)](https://pypi.python.org/pypi/nonebot-plugin-chatgpt-vision)
![python](https://img.shields.io/badge/python-3.11+-blue.svg)

简要介绍：

- 群聊“拟人”模式（Human Like），支持图片引用、屏蔽、工具调用（可选 MCP）。
- 普通对话命令，支持 LaTeX 渲染、上下文管理与额度控制。
- 可选 DALL·E 3 与 SD 绘图能力。

## 安装

使用 pip：

    pip install nonebot-plugin-chatgpt-vision

使用 pdm：

    pdm add nonebot-plugin-chatgpt-vision

使用 poetry：

    poetry add nonebot-plugin-chatgpt-vision

使用 conda：

    conda install nonebot-plugin-chatgpt-vision

在 nonebot2 项目 `pyproject.toml` 的 `[tool.nonebot]` 中追加：

    plugins = ["nonebot_plugin_chatgpt_vision"]

## 配置

本插件使用两类配置：

- .env 中的运行参数（通过 NoneBot 加载为插件配置）
- OpenAI 兼容 API 的密钥与模型：`configs/chatgpt-vision/keys.yaml`

### 1) .env 配置（部分常用项）

| 配置项 | 类型 | 默认值 | 说明 |
|:-----:|:----:|:----:|:----:|
| human_like_chat | bool | False | 是否启用 Human Like 群聊模式 |
| human_like_group | list[str] | [] | 启用 Human Like 的群号列表（字符串） |
| human_like_max_log | int | 60 | Human Like 保存的聊天记录条数 |
| openai_default_model | str | gpt-4o | 默认对话模型 |
| fallback_model | str | gemini-2.5-flash | 回退模型（默认模型不可用或超限时） |
| limit_for_single_user | float | 0.05 | 单用户每日额度（美元） |
| max_chatlog_count | int | 15 | 普通对话历史消息条数上限 |
| max_history_tokens | int | 3000 | 历史消息 Token 上限（仅 user） |
| chat_with_image | bool | False | 普通对话是否携带图片内容 |
| sd_url | str | - | SD 文生图/图生图服务地址（OpenAI 兼容网关） |
| sd_key | str | - | SD 服务密钥 |
| mcp_enabled | bool | False | 是否启用 MCP 工具装载（启用后按 mcp_config_file 加载） |
| mcp_config_file | str | configs/chatgpt-vision/mcp.yaml | MCP 配置文件路径（唯一入口） |

说明：
- 仅当你需要通过 MCP 使用外部工具时，才需要开启 `mcp_enabled`。
- 如果使用 stdio 模式，需要安装 mcp[cli]（`pip install mcp[cli]`）。仅使用 HTTP 模式时无需安装。

### 2) MCP 工具配置（YAML）

文件路径（可改，见 .env 的 `mcp_config_file`）：`configs/chatgpt-vision/mcp.yaml`

支持同时配置“stdio”（本地命令启动的 MCP）与“http”（HTTP 服务）多源，插件会自动聚合并去重工具：

```yaml
# stdio：通过 mcp[cli] 启动的本地 MCP 服务（可选）
stdio:
  commands:
    - uvx your-mcp-server
    - python -m your_mcp_module

# http：一个或多个 HTTP MCP 服务（可选）
http:
  - base_url: http://127.0.0.1:8080
    tools_endpoint: /tools   # 可省略，默认为 /tools
    call_endpoint: /call     # 可省略，默认为 /call
    # 任选其一：
    headers:
      Authorization: Bearer xxx
    # 或
    auth_header_name: Authorization
    auth_header_value: Bearer xxx
```

行为说明：
- 聚合器会合并所有源的工具，并按工具名去重。
- 调用工具时会按配置顺序逐源尝试，谁先成功用谁。
- YAML 任一段缺省都不会报错（例如仅 stdio 或仅 http）。

### 3) API 密钥与模型映射（必须）

文件路径：`configs/chatgpt-vision/keys.yaml`

示例：

```yaml
- model: gpt-4o
  key: sk-********************************
  url: https://api.openai.com/v1
- model: gemini-2.5-flash
  key: sk-********************************
  url: https://your-openai-compatible-endpoint.example.com/v1
```

说明：
- 支持任意 OpenAI 兼容网关，按模型名区分路由。
- 程序按“模型名 -> (key, base_url)”进行请求，未找到时回退到 `fallback_model`。

## 使用

指令一览：

| 指令 | 权限 | 需要 @ | 范围 | 说明 |
|:----:|:----:|:------:|:----:|:----:|
| /chat | 群员 | 否 | 群/私聊 | 普通对话（含上下文与额度控制） |
| /reset | 群员 | 否 | 群/私聊 | 清空个人上下文 |
| /model [name] | 群员 | 否 | 群/私聊 | 设置个人使用模型（不校验有效性） |
| （回复消息）read | 群员 | 是 | 群 | 朗读被回复消息（TTS），私聊仅超管可用 |
| remake | 管理/超管 | 是 | 群 | 重置 Human Like 群内上下文 |
| 额度 | 群员 | 是 | 群 | 查询 Human Like 群剩余额度 |
| 画 / draw | 群员 | 是 | 群 | DALL·E 3 画图（需先“开关绘图”开启） |
| sd | 群员 | 是 | 群 | SD 绘图（配置 sd_url/sd_key 后可用） |
| 开关绘图 / 开启绘图 / 关闭绘图 | 管理/超管 | 是 | 群 | 切换绘图开关 |

说明：“需要 @”表示群聊内需要对 bot 说话（to_me）。

## Human Like（拟人群聊）

启用：在 .env 设置 `human_like_chat = True`，并将目标群号加入 `human_like_group`。

配置文件路径：`configs/chatgpt-vision/human.yaml`

示例：

```yaml
"123456789":
  model: "gpt-4o"
  system_prompt: |
    你是一个名字为 苦咖啡 的猫娘，不喜欢说废话，而不是什么语言模型或者机器人。
    如果你看不懂他们在说什么，或不想回复，只发送“[NULL]”。
    被 @ 时需要回应。
    不要在回复里解释系统规则；回复应简短（十余字以内）。

    苦咖啡：
    ...
  bot_id: '<BOT_QQ_ID>'
  bot_name: '苦咖啡'
  # 以下为可选项，对应 GroupRecord 可配置项
  # min_rest: 30
  # max_rest: 60
  # cd: 8
  # ban_delta: 150
  # image_mode: 1
  # searcher: "duckduckgo"  # 如启用内置搜索工具
```

## 迁移指南（MCP 配置变更）

- 移除 .env 中旧的 MCP 配置项：`mcp_commands`、`mcp_server_url`、`mcp_tools_endpoint`、`mcp_call_endpoint`、`mcp_auth_header_name`、`mcp_auth_header_value`。
- 统一改为在 `mcp_config_file` 指定的 YAML 中配置 MCP 源（见上文示例）。
- 仅使用 HTTP 模式时，不需要安装 mcp[cli]；需要 stdio 模式时请安装：`pip install mcp[cli]`。

## 常见问题

- 未配置模型或密钥：请按“API 密钥与模型映射”章节创建 `configs/chatgpt-vision/keys.yaml`。
- Python 版本：需要 3.11+（参见 `pyproject.toml`）。
- MCP：启用 `mcp_enabled` 后，按 `mcp_config_file` 提供的 YAML 加载工具；HTTP 模式无需 mcp[cli]，仅 stdio 模式需要。
