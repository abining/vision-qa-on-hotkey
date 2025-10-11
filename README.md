# Vision QA on Hotkey

一个基于热键触发的视觉问答系统，通过按"5"键快速截图并调用AI模型回答问题，支持Web界面查看结果和历史记录。

## 功能特性

- 🎯 **一键触发**：按"5"键即可截图并获取AI回答
- 🤖 **智能识别**：基于火山引擎豆包模型的视觉问答能力
- 🌐 **Web界面**：实时查看最新识别结果
- 📊 **性能监控**：显示截图和AI推理耗时
- ⚙️ **灵活配置**：支持自定义截图区域和环境变量配置

## 安装和使用

### 环境要求

- Python 3.7+
- macOS/Windows/Linux

### 安装依赖

```bash
pip install -r requirements.txt
```

### 环境配置

1. 复制环境变量模板：
```bash
cp .env.example .env
```

2. 获取火山的key，并且获取对应的模型。

![](https://s2.loli.net/2025/10/11/I2wfGhU5aJyODZo.png)

![](https://s2.loli.net/2025/10/11/6E1JK9yrTZ5SqgD.png)

3. 编辑 `.env` 文件，配置您的API密钥和截图区域，API秘钥是图1中的API Key，点击小眼睛即可查看并复制：

```env
VOLC_API_KEY=your_api_key_here
```

### 运行程序

```bash
python script.py
```

程序启动后：
- 按"5"键触发截图和AI问答
- 访问 http://localhost:8003 查看结果
- 按 Ctrl+C 退出程序

### 自定义截图区域

```bash
python script.py --left 100 --top 100 --width 800 --height 600
```

## 环境变量说明

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `PORT` | Web服务端口 | 8003 |
| `LOG_LEVEL` | 日志级别 | INFO |
| `VOLC_API_KEY` | 火山引擎API密钥 | 必填 |
| `VOLC_BASE_URL` | API基础URL | 火山引擎默认URL |
| `VOLC_MODEL` | 使用的模型 | doubao-1-5-vision-pro-250328 |
| `VOLC_TEMPERATURE` | 模型温度参数 | 0.2 |
| `VOLC_MAX_TOKENS` | 最大token数 | 无限制 |
| `SCREENSHOT_LEFT` | 截图区域左上角X坐标 | 200 |
| `SCREENSHOT_TOP` | 截图区域左上角Y坐标 | 200 |
| `SCREENSHOT_WIDTH` | 截图宽度 | 1200 |
| `SCREENSHOT_HEIGHT` | 截图高度 | 800 |

## TODO

- [ ] 监听语音，给出AI答案
- [ ] 历史回顾功能（查看图片和答案）

## 技术栈

- **截图**：pyautogui
- **HTTP请求**：requests
- **图像处理**：Pillow
- **键盘监听**：pynput
- **环境变量**：python-dotenv
- **Web服务**：内置HTTP服务器

## 许可证

MIT License
