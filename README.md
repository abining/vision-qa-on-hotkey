# Vision QA on Hotkey

一个基于热键触发的视觉问答系统，通过按"5"键截图并调用视觉模型回答问题，使用 Web 界面查看最新结果。

## 功能特性

- 🎯 **一键触发**：按"5"键即可截图并获取AI回答
- 🤖 **多模型接口**：支持 OpenAI 兼容的 Chat Completions 和 Responses 接口，通过配置切换供应商和模型
- 🌐 **Web界面**：实时查看最新识别结果
- 📊 **性能监控**：显示截图和AI推理耗时
- ⚙️ **灵活配置**：支持自定义截图区域和环境变量配置
- 🧪 **模拟截图**：从本地图片裁剪区域，无需桌面权限即可测试识别流程
- ⏱️ **简短回答**：可配置提示词、输出 token 上限、请求超时及重试次数，避免重复触发堆积请求
- 💾 **自动归档**：每次识别保存截图、答案和请求信息，运行日志自动轮转

## 安装和使用

### 环境要求

- **Python 3.9+** (推荐 Python 3.9 或更高版本)
- **操作系统**：macOS/Windows/Linux
- **测试环境**：Python 3.9 ✅ (已验证兼容)

### 安装依赖

```bash
pip install -r requirements.txt
```

### 环境配置

1. 首次配置时复制模板（已有 `.env2` 时直接编辑，不要覆盖）：
```bash
cp .env.example .env2
```

2. 编辑 `.env2`，填写中转站或模型供应商配置：

```env
API_KEY=your_api_key_here
API_BASE_URL=https://api.330103.xyz/v1
API_MODEL=gemini-3.1-flash-lite
API_STYLE=chat_completions
API_MAX_TOKENS=128
API_REASONING_EFFORT=minimal
API_TIMEOUT=30
API_MAX_RETRIES=0
```

`API_BASE_URL` 是基础 URL，SDK 会追加 `/chat/completions` 或 `/responses`。模型必须支持图片输入，服务端必须支持所选接口；本程序不直接调用 Gemini / Anthropic 的原生专有协议。此处的模型名是中转站接收的标识，不代表已核验其底层模型身份。

默认优先读取程序目录的 `.env2`，不存在时读取 `.env`；两份文件不会合并。同名进程环境变量优先于文件值。也可用 `--env` 指定其他配置。原有 `VOLC_*` 配置仍可读取，只有旧密钥配置时默认使用原来的 Responses 模式；`DATASET` 原本没有发送给 API，本次仍未接入知识库检索。

密钥只保存在本地配置，不要提交 `.env` / `.env2`。如果文件已经被 Git 跟踪或暂存，添加忽略规则也不会自动将其移除。

### 运行程序

```bash
python script.py
# 显式指定当前中转站配置
python script.py --env .env2
# 使用原有火山配置
python script.py --env .env
```

程序启动后：
- 按"5"键触发截图和AI问答
- 访问 http://localhost:8003 查看结果
- 网页每 1 秒刷新，展示最新图片、答案、耗时和请求编号；每次识别的完整记录自动保存在磁盘。
- 按 Ctrl+C 退出程序

### 自定义截图区域

```bash
python script.py --left 100 --top 100 --width 800 --height 600
```

### 模拟截图与单次识别

用已有图片模拟整个屏幕，不访问桌面，也不启动热键监听或网页：

```bash
python script.py --env .env2 --image screen.png --once
```

未指定任何区域参数时，`--image` 使用整张图片；指定区域参数时，未填写的参数使用配置文件中的值。先检查裁剪区域，不调用 API：

```bash
python script.py --image screen.png --left 100 --top 100 --width 400 --height 300 --capture-only crop.png
```

真实桌面也可以单次截图识别：

```bash
python script.py --env .env2 --once
```

函数调用示例（输入也可以是 `PIL.Image.Image`）：

```python
from script import configure, simulate_capture_region, ask_ai_with_image

configure(".env2")
image_bytes, capture_ms = simulate_capture_region(
    "screen.png", left=100, top=100, width=400, height=300
)
answer, infer_ms = ask_ai_with_image(image_bytes)
print(answer, capture_ms, infer_ms)
```

`simulate_capture_region` 返回 PNG 字节及裁剪耗时，超出图片范围会报错。省略宽高时截取从左上坐标开始的剩余区域。真实截图使用 `capture_region(left, top, width, height)`。保留 `ask_doubao_with_image` 作为旧函数名的别名，实际使用当前模型配置。

### 截图保存与日志

热键触发、`--once` 和直接调用 `ask_ai_with_image` 都会自动归档。默认保存到程序目录下的 `data/`，不受启动命令所在目录影响：

```text
data/
  requests/
    2026-10-29/
      时间_微秒_随机编号/
        screenshot.png    原始截图，在调用 API 前保存
        input.png         图片重新编码或缩小时，保存实际发送的版本
        record.json       本次识别的参数、状态、答案、耗时和错误
  logs/
    app.log               当前运行日志
    app.log.1             轮转备份，最多 .1 至 .5
```

原图与实际发送图片完全相同时不重复保存，`record.json` 的 `inputImage.file` 会指向 `screenshot.png`。JSON 还包括图片尺寸、字节数及 SHA-256、截图坐标、实际提示词、模型与接口、思考量、输出上限、服务端请求编号与 token 用量（服务端提供时）。运行日志记录时间、级别、线程、识别编号、发送与结束阶段、耗时和错误堆栈；答案全文在该次 `record.json` 中。

API 超时或报错时，已经保存的截图会保留，记录状态为 `failed`；截图本身失败时仍保存错误记录，但没有图片。请求前先写入 `requesting` 状态，结果用临时文件原子替换；如果进程被强制终止，未完成记录可能停留在 `started` / `requesting`，不应视为成功。若归档目录不可写或磁盘满，程序会显示错误，不会继续发起没有截图记录的 API 请求。

`LOG_LEVEL=INFO` 适合正常使用；`DEBUG` 还记录网页访问。默认每份运行日志最大 5 MiB，保留 5 份备份。密钥、Bearer 凭证和图片 base64 在本程序日志与 JSON 文本中脱敏。截图及识别记录默认长期保存，不会随日志轮转删除；可按日期自行整理。默认 `data/` 已加入 Git 忽略，自定义到其他目录时需自行排除。`--capture-only` 仍只把截图保存到显式指定的位置，不创建模型对话记录。

### 是否携带历史对话

**不会。每次请求独立，只包含当前提示词和当前图片。** Chat Completions 的 `messages` 每次新建，只有一条 `user` 消息；Responses 的 `input` 同样只有当前消息，没有发送 `previous_response_id` 或 `conversation`。复用 SDK 客户端用于连接复用，程序没有用它串联响应。

`history` 仅保存本地结果摘要，磁盘归档也不会被读入下一次请求。每份 JSON 明确记录 `context.historyMessages=0`。测试通过向历史、上次答案和响应 ID 中放入标记，再检查连续两次请求体，验证两种接口均没有携带旧内容。如果当前截图本身包含旧题目或旧答案，模型仍能从这张图片看到它们；第三方中转站内部如何处理数据不在本项目代码的可见范围内。

## 环境变量说明

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `PORT` | Web服务端口 | 8003 |
| `LOG_LEVEL` | 日志级别 | INFO |
| `DATA_DIR` | 截图、识别记录及运行日志的根目录；相对路径以程序目录为基准 | data |
| `LOG_MAX_BYTES` | 单份运行日志的轮转大小，字节 | 5242880（5 MiB） |
| `LOG_BACKUP_COUNT` | 运行日志备份份数；不影响截图归档 | 5 |
| `API_KEY` | API 密钥；也支持 `OPENAI_API_KEY`、`VOLC_API_KEY`、`ARK_API_KEY`、`VOLCENGINE_API_KEY` | 必填 |
| `API_BASE_URL` | API 基础 URL；也支持 `OPENAI_BASE_URL`、`VOLC_BASE_URL` | OpenAI 基础 URL；旧配置默认火山 URL |
| `API_MODEL` | 模型 ID；也支持 `OPENAI_MODEL`、`VOLC_MODEL` | 通用配置必填；旧配置保留豆包默认模型 |
| `API_STYLE` | `chat_completions` 或 `responses` | 通用配置为 `chat_completions`；只有旧密钥时为 `responses` |
| `API_TEMPERATURE` | 温度；也支持 `VOLC_TEMPERATURE`；留空不发送 | 0.2 |
| `API_MAX_TOKENS` | 最大输出 token；也支持 `VOLC_MAX_TOKENS`；留空不发送 | 256；速度优先模板为 128 |
| `API_TOKEN_PARAMETER` | Chat 模式的上限字段：`max_tokens` 或 `max_completion_tokens` | max_tokens |
| `API_REASONING_EFFORT` | 思考量提示；Chat 模式发送 `reasoning_effort`，Responses 模式发送 `reasoning.effort` | 默认不发送；速度优先模板为 minimal |
| `API_TIMEOUT` | 网络请求超时，单位秒；不是端到端耗时保证 | 30 |
| `API_MAX_RETRIES` | 自动重试次数 | 0 |
| `AI_PROMPT` | 视觉问答提示词 | 默认 80 字以内；速度优先模板选择题只给选项，其他题尽量 40 字以内 |
| `IMAGE_MAX_SIDE` | 发给模型的图片最长边；等比例缩小，0 表示不缩放 | 1280 |
| `SCREENSHOT_LEFT` | 截图区域左上角X坐标 | 200 |
| `SCREENSHOT_TOP` | 截图区域左上角Y坐标 | 200 |
| `SCREENSHOT_WIDTH` | 截图宽度 | 1200 |
| `SCREENSHOT_HEIGHT` | 截图高度 | 800 |

同类配置优先采用 `API_*`，其次 `OPENAI_*`，最后 `VOLC_*`。切换供应商时建议分别保存配置文件，通过 `--env` 选择，每次启动使用一家供应商和一个模型。Responses 模式自动使用 `max_output_tokens`；如果新模型不接受温度，可以设置 `API_TEMPERATURE=`。若回答被截断或没有正文，增大 `API_MAX_TOKENS`；文字过小则提高 `IMAGE_MAX_SIDE` 或设置为 0。

### 优先响应速度

速度优先模板使用 `gemini-3.1-flash-lite`，请求 `minimal` 思考量，输出上限为 128 token，选择题只输出选项、其他题尽量 40 字以内。实际模型以启动时读取的配置及日志为准。`API_REASONING_EFFORT` 的可用值取决于模型与中转站，`minimal` 不等于保证完全关闭思考；切换到不支持该参数的模型时设为 `API_REASONING_EFFORT=`，程序就不发送这个字段。

输出上限主要约束回答长度，调低超时时间只会让等待更早失败，不能让模型更快完成。网页刷新已从 2 秒改为 1 秒，减少完整答案生成后的展示等待。当前截图区域无需缩小；如果进一步降低图片尺寸或清晰度，应检查小字是否仍能正确识别。复杂推理题可提高思考量和 token 上限，但需重新验证准确率及耗时。

### 验证

```bash
python -m unittest discover -s tests -v
```

24 项离线测试使用模拟 HTTP 响应，不消耗 API 额度，覆盖配置选择、两种接口及思考量参数、裁剪边界、空响应、超时、重复触发、截图归档、日志轮转与脱敏、归档失败处理，以及连续请求不引用历史内容。

2026-10-29 使用同一张 640×320 合成算术题图片测试当前中转站，以下均为完整 API 请求耗时，不含网页显示等待：

| 配置 | 实测耗时 | 结果 |
|------|----------|------|
| 原 `gemini-3.8-flash-high`，256 token，原提示词（上次单次测试） | 7.09 秒 | 正确，附简短理由 |
| `gemini-3.1-flash-lite`，256 token，原提示词（本次单次测试） | 5.26 秒 | 正确，附简短理由 |
| `gemini-3.1-flash-lite`，minimal，128 token，只输出答案（本次 3 次测试） | 1.99 / 4.81 / 5.37 秒 | 三次均正确返回 `B` |

快速配置三次平均约 4.06 秒，中位数约 4.81 秒；样本少且中转站存在波动，不能将差异全部归因于思考量参数，也不保证每次两秒完成。中转站接受了带 `reasoning_effort` 的请求，但是否将该字段原样传给上游无法由这次响应确认；这些测试也不能证明复杂题的准确率。

## TODO

- [ ] 监听语音，给出AI答案
- [ ] 历史回顾功能（查看图片和答案）

## 技术栈

- **截图**：pyautogui
- **模型调用**：OpenAI Python SDK
- **图像处理**：Pillow
- **键盘监听**：pynput
- **环境变量**：python-dotenv
- **Web服务**：内置HTTP服务器

## 发版流程

```
git add .
git commit -m "fix: requirements.txt format"
git tag -a v1.0 -m "发布1.0版本：修复一些bug和实现数据集引入"
git push origin v1.0
```

## 许可证

MIT License
