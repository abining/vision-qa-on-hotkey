# -*- coding: utf-8 -*-
"""
Python 版本的视觉问答系统
功能：按 5 键 → 截图 → 调用 AI → 显示结果
"""

import argparse
import base64
import hashlib
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html import escape
from http.server import BaseHTTPRequestHandler, HTTPServer
from io import BytesIO
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import Lock, Thread
from typing import Optional
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from PIL import Image
from dotenv import dotenv_values
from openai import OpenAI

# ------------------ 配置 ------------------
DEFAULT_PROMPT = "阅读图片中的问题，用中文直接给出答案。选择题只给选项和一句简短理由；其他问题尽量在80字以内，不重复题目，不展开推导。"


@dataclass
class Settings:
    api_key: str = field(default="", repr=False)
    base_url: str = "https://api.openai.com/v1"
    model: str = ""
    api_style: str = "chat_completions"
    temperature: Optional[float] = 0.2
    max_tokens: Optional[int] = 256
    token_parameter: str = "max_tokens"
    reasoning_effort: Optional[str] = None
    timeout: float = 30
    max_retries: int = 0
    prompt: str = DEFAULT_PROMPT
    image_max_side: int = 1280
    port: int = 8003
    log_level: str = "INFO"
    data_dir: Path = field(default_factory=lambda: Path(__file__).resolve().parent / "data")
    log_max_bytes: int = 5 * 1024 * 1024
    log_backup_count: int = 5
    region: tuple = (200, 200, 1200, 800)
    env_file: Optional[Path] = None

    @classmethod
    def from_env(cls, env_file=None):
        base_dir = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
        path = Path(env_file) if env_file is not None else base_dir / ".env2"
        if env_file is None and not path.is_file():
            path = base_dir / ".env"
        if env_file is not None and not path.is_file():
            raise ValueError(f"配置文件不存在：{path}")
        values = {**dotenv_values(path), **os.environ}

        def pick(*names, default=None):
            for name in names:
                if values.get(name):
                    return values[name].strip()
            return default

        legacy = not pick("API_KEY", "OPENAI_API_KEY") and bool(pick("VOLC_API_KEY", "ARK_API_KEY", "VOLCENGINE_API_KEY"))
        base_url = pick("API_BASE_URL", "OPENAI_BASE_URL", "VOLC_BASE_URL", default="https://ark.cn-beijing.volces.com/api/v3" if legacy else "https://api.openai.com/v1").rstrip("/")
        # SDK 会追加接口路径；也兼容旧配置误填的完整 endpoint。
        for suffix in ("/chat/completions", "/responses"):
            if base_url.endswith(suffix):
                base_url = base_url[:-len(suffix)]
                break
        temperature = values.get("API_TEMPERATURE", values.get("VOLC_TEMPERATURE", "0.2"))
        max_tokens = values.get("API_MAX_TOKENS", values.get("VOLC_MAX_TOKENS", "256"))
        config = cls(
            api_key=pick("API_KEY", "OPENAI_API_KEY", "VOLC_API_KEY", "ARK_API_KEY", "VOLCENGINE_API_KEY", default=""),
            base_url=base_url,
            model=pick("API_MODEL", "OPENAI_MODEL", "VOLC_MODEL", default="doubao-1-5-vision-pro-250328" if legacy else ""),
            api_style=pick("API_STYLE", default="responses" if legacy else "chat_completions"),
            temperature=float(temperature) if temperature and temperature.strip() else None,
            max_tokens=int(max_tokens) if max_tokens and max_tokens.strip() else None,
            token_parameter=pick("API_TOKEN_PARAMETER", default="max_tokens"),
            reasoning_effort=pick("API_REASONING_EFFORT"),
            timeout=float(pick("API_TIMEOUT", default="30")),
            max_retries=int(pick("API_MAX_RETRIES", default="0")),
            prompt=pick("AI_PROMPT", default=DEFAULT_PROMPT),
            image_max_side=int(pick("IMAGE_MAX_SIDE", default="1280")),
            port=int(pick("PORT", default="8003")),
            log_level=pick("LOG_LEVEL", default="INFO").upper(),
            data_dir=Path(pick("DATA_DIR", default="data")).expanduser(),
            log_max_bytes=int(pick("LOG_MAX_BYTES", default=str(5 * 1024 * 1024))),
            log_backup_count=int(pick("LOG_BACKUP_COUNT", default="5")),
            region=tuple(int(pick(name, default=str(default))) for name, default in zip(
                ("SCREENSHOT_LEFT", "SCREENSHOT_TOP", "SCREENSHOT_WIDTH", "SCREENSHOT_HEIGHT"), (200, 200, 1200, 800))),
            env_file=path,
        )
        if config.api_style not in ("chat_completions", "responses"):
            raise ValueError("API_STYLE 只能是 chat_completions 或 responses")
        if config.token_parameter not in ("max_tokens", "max_completion_tokens"):
            raise ValueError("API_TOKEN_PARAMETER 只能是 max_tokens 或 max_completion_tokens")
        if config.reasoning_effort not in (None, "none", "minimal", "low", "medium", "high", "xhigh", "max"):
            raise ValueError("API_REASONING_EFFORT 必须留空或为 none/minimal/low/medium/high/xhigh/max")
        if config.timeout <= 0 or config.max_retries < 0 or config.image_max_side < 0:
            raise ValueError("API_TIMEOUT 必须大于0，API_MAX_RETRIES 和 IMAGE_MAX_SIDE 不能小于0")
        if config.max_tokens is not None and config.max_tokens <= 0:
            raise ValueError("API_MAX_TOKENS 必须大于0，或留空以使用服务端默认值")
        if config.log_level not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            raise ValueError("LOG_LEVEL 必须为 DEBUG/INFO/WARNING/ERROR/CRITICAL")
        if config.log_max_bytes <= 0 or config.log_backup_count < 1:
            raise ValueError("LOG_MAX_BYTES 和 LOG_BACKUP_COUNT 必须大于0")
        if not config.data_dir.is_absolute():
            config.data_dir = base_dir / config.data_dir
        config.data_dir = config.data_dir.resolve()
        return config

# 全局状态
settings = None
api_client = None
latest = None
history = []
last_trigger_at = 0
args = None  # 命令行参数
trigger_lock = Lock()
logger = logging.getLogger("vision_qa")
logger.propagate = False
logger.addHandler(logging.NullHandler())


def configure(env_file=None):
    global settings, api_client
    config = Settings.from_env(env_file)
    if api_client is not None:
        api_client.close()
        api_client = None
    settings = config
    setup_logging(config)
    return config


def get_settings():
    return settings if settings is not None else configure()


# ------------------ 日志 ------------------
def redact_text(value):
    text = str(value)
    if settings is not None and settings.api_key:
        text = text.replace(settings.api_key, "[REDACTED]")
    text = re.sub(r"\bsk-[A-Za-z0-9_-]+", "[REDACTED]", text)
    text = re.sub(r"(?i)(Bearer\s+)[^\s\"',}]+", r"\1[REDACTED]", text)
    return re.sub(r"data:image/[^;,\s]+;base64,[A-Za-z0-9+/=]+", "[IMAGE_DATA]", text)


def safe_data(value):
    if isinstance(value, dict):
        return {key: safe_data(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe_data(item) for item in value]
    return redact_text(value) if isinstance(value, str) else value


class SafeLogFormatter(logging.Formatter):
    def format(self, record):
        # 在格式化堆栈之后脱敏，避免异常文本包含密钥或图片 base64。
        return redact_text(super().format(record))


def setup_logging(config):
    log_dir = config.data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(log_dir / "app.log", maxBytes=config.log_max_bytes,
                                       backupCount=config.log_backup_count, encoding="utf-8")
    console_handler = logging.StreamHandler(sys.stdout)
    formatter = SafeLogFormatter("%(asctime)s %(levelname)s [%(threadName)s] %(message)s",
                                 datefmt="%Y-%m-%dT%H:%M:%S%z")
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    for handler in (console_handler, file_handler):
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    logger.setLevel(config.log_level)


def log_info(msg):
    logger.info(msg)


def log_error(msg, exc_info=False):
    logger.error(msg, exc_info=exc_info)


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class RecognitionRecord:
    """每次识别独立归档；只记录本次请求信息，不用于模型上下文。"""

    def __init__(self, config, region=None, source="function"):
        now = datetime.now().astimezone()
        self.started = time.perf_counter()
        self.api_started = None
        self.request_id = now.strftime("%H%M%S_%f") + "_" + uuid4().hex[:12]
        self.directory = config.data_dir / "requests" / now.strftime("%Y-%m-%d") / self.request_id
        self.directory.mkdir(parents=True, exist_ok=False)
        self.path = self.directory / "record.json"
        url = urlsplit(config.base_url)
        safe_url = urlunsplit((url.scheme, url.netloc.rsplit("@", 1)[-1], url.path, "", ""))
        self.data = {
            "schemaVersion": 1, "requestId": self.request_id, "status": "started", "stage": "capture",
            "startedAt": utc_now(), "finishedAt": None,
            "model": config.model, "apiStyle": config.api_style, "baseUrl": safe_url,
            "prompt": config.prompt, "region": list(region) if region else None, "source": source,
            "parameters": {"temperature": config.temperature, "maxTokens": config.max_tokens,
                           "tokenParameter": config.token_parameter if config.api_style == "chat_completions" else "max_output_tokens",
                           "reasoningEffort": config.reasoning_effort, "timeout": config.timeout,
                           "maxRetries": config.max_retries, "imageMaxSide": config.image_max_side},
            "context": {"historyMessages": 0, "messageCount": 1, "previousResponseId": None},
            "screenshot": None, "inputImage": None, "answer": None, "error": None,
            "durations": {}, "response": {},
        }
        self.save()
        log_info(f"[{self.request_id}] 识别开始 model={config.model} api={config.api_style} region={region} historyMessages=0")

    def save(self):
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(safe_data(self.data), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path)

    def save_image(self, image_bytes, field_name, filename):
        # 先落盘，再解码校验；API 失败或输入图片损坏时仍保留现场。
        path = self.directory / filename
        path.write_bytes(image_bytes)
        info = {"file": filename, "bytes": len(image_bytes), "sha256": hashlib.sha256(image_bytes).hexdigest()}
        self.data[field_name] = info
        with Image.open(BytesIO(image_bytes)) as image:
            info["width"], info["height"] = image.size

    def finish(self, answer=None, error=None):
        self.data["status"] = "failed" if error is not None else "completed"
        self.data["finishedAt"] = utc_now()
        self.data["durations"]["totalMs"] = int((time.perf_counter() - self.started) * 1000)
        self.data["answer"] = answer
        if error is not None:
            self.data["error"] = {"type": type(error).__name__, "message": redact_text(error),
                                  "httpStatus": getattr(error, "status_code", None),
                                  "requestId": getattr(error, "request_id", None)}
        self.save()
        log_info(f"[{self.request_id}] 识别结束 status={self.data['status']} durations={self.data['durations']} record={self.path}")


# ------------------ 截图 ------------------
def validate_region(left, top, width, height):
    if left < 0 or top < 0 or width <= 0 or height <= 0:
        raise ValueError("left、top 不能小于0，width、height 必须大于0")


def capture_region(left, top, width, height, source_image=None):
    """返回指定区域的 PNG 字节和耗时；source_image 可为本地路径或 PIL 图片。"""
    validate_region(left, top, width, height)
    start_time = time.perf_counter()
    try:
        if source_image is None:
            import pyautogui

            screenshot = pyautogui.screenshot(region=(left, top, width, height))
        else:
            if isinstance(source_image, Image.Image):
                source = source_image.copy()
            else:
                with Image.open(source_image) as opened:
                    source = opened.copy()
            with source:
                if left + width > source.width or top + height > source.height:
                    raise ValueError(f"截图区域超出源图片尺寸 {source.width}x{source.height}")
                screenshot = source.crop((left, top, left + width, top + height))
        buf = BytesIO()
        with screenshot:
            screenshot.convert("RGB").save(buf, format='PNG')
        img_bytes = buf.getvalue()
        duration_ms = int((time.perf_counter() - start_time) * 1000)
        log_info(f"截图完成：{len(img_bytes)} bytes，耗时 {duration_ms}ms")
        return img_bytes, duration_ms
    except Exception as e:
        raise RuntimeError(f"截图失败: {e}")


def simulate_capture_region(source_image, left=0, top=0, width=None, height=None):
    """用本地图片模拟屏幕；默认截取从 (left, top) 开始的剩余区域，不访问桌面。"""
    if isinstance(source_image, Image.Image):
        size = source_image.size
    else:
        with Image.open(source_image) as source:
            size = source.size
    return capture_region(left, top, size[0] - left if width is None else width,
                          size[1] - top if height is None else height, source_image=source_image)


# ------------------ 调用 AI API ------------------
def get_api_client():
    global api_client
    config = get_settings()
    if not config.api_key:
        raise ValueError("未配置 API_KEY（也支持 OPENAI_API_KEY / VOLC_API_KEY）")
    if not config.model:
        raise ValueError("未配置 API_MODEL")
    if api_client is None:
        api_client = OpenAI(api_key=config.api_key, base_url=config.base_url,
                            timeout=config.timeout, max_retries=config.max_retries)
    return api_client


def ask_ai_with_image(image_bytes, record=None):
    """归档当前图片并调用模型；返回答案和请求耗时，不携带历史消息。"""
    record = record if record is not None else RecognitionRecord(get_settings())
    try:
        record.data["stage"] = "save_screenshot"
        record.save_image(image_bytes, "screenshot", "screenshot.png")
        record.save()
        return _request_ai_with_image(image_bytes, record)
    except Exception as error:
        if record.api_started is not None and "inferMs" not in record.data["durations"]:
            record.data["durations"]["inferMs"] = int((time.perf_counter() - record.api_started) * 1000)
        log_error(f"[{record.request_id}] 模型调用失败 stage={record.data['stage']}: {error}", exc_info=True)
        try:
            record.finish(error=error)
        except OSError:
            log_error(f"[{record.request_id}] 识别记录写入失败：{record.path}", exc_info=True)
        raise


def _request_ai_with_image(image_bytes, record):
    config = get_settings()
    record.data["stage"] = "prepare_request"
    client = get_api_client()
    with Image.open(BytesIO(image_bytes)) as image:
        if config.image_max_side:
            image.thumbnail((config.image_max_side, config.image_max_side))
        buf = BytesIO()
        image.convert("RGB").save(buf, format="PNG")
    input_bytes = buf.getvalue()
    if input_bytes == image_bytes:
        record.data["inputImage"] = dict(record.data["screenshot"])
    else:
        record.save_image(input_bytes, "inputImage", "input.png")
    image_url = "data:image/png;base64," + base64.b64encode(input_bytes).decode("ascii")
    kwargs = {"model": config.model}
    if config.temperature is not None:
        kwargs["temperature"] = config.temperature

    record.data["status"] = "requesting"
    record.data["stage"] = "api_request"
    record.save()
    log_info(f"[{record.request_id}] 发送请求 imageBytes={len(input_bytes)} historyMessages=0")
    start_time = record.api_started = time.perf_counter()
    if config.api_style == "chat_completions":
        if config.reasoning_effort:
            kwargs["reasoning_effort"] = config.reasoning_effort
        kwargs["messages"] = [{"role": "user", "content": [
            {"type": "text", "text": config.prompt},
            {"type": "image_url", "image_url": {"url": image_url}},
        ]}]
        if config.max_tokens is not None:
            kwargs[config.token_parameter] = config.max_tokens
        response = client.chat.completions.create(**kwargs)
        record.data["response"]["finishReason"] = response.choices[0].finish_reason if response.choices else None
        content = response.choices[0].message.content if response.choices else None
        if response.choices and response.choices[0].finish_reason == "length":
            logger.warning(f"[{record.request_id}] 回答达到 token 上限；如被截断，请增大 API_MAX_TOKENS")
    else:
        if config.reasoning_effort:
            kwargs["reasoning"] = {"effort": config.reasoning_effort}
        kwargs["input"] = [{"role": "user", "content": [
            {"type": "input_text", "text": config.prompt},
            {"type": "input_image", "image_url": image_url},
        ]}]
        if config.max_tokens is not None:
            kwargs["max_output_tokens"] = config.max_tokens
        response = client.responses.create(**kwargs)
        record.data["response"]["status"] = response.status
        content = response.output_text
        if response.status == "incomplete":
            logger.warning(f"[{record.request_id}] 回答未完成；请检查 token 上限或服务端限制")
    record.data["durations"]["inferMs"] = int((time.perf_counter() - start_time) * 1000)
    record.data["stage"] = "parse_response"
    usage = getattr(response, "usage", None)
    record.data["response"].update({
        "id": getattr(response, "id", None), "requestId": getattr(response, "_request_id", None),
        "model": getattr(response, "model", None),
        "usage": usage.model_dump(exclude_none=True) if usage is not None else None,
    })
    if not content or not content.strip():
        raise RuntimeError("模型未返回文字答案，请检查视觉支持、模型权限及 token 上限")
    infer_ms = record.data["durations"]["inferMs"]
    record.data["stage"] = "save_result"
    record.finish(answer=content.strip())
    return content.strip(), infer_ms


def ask_doubao_with_image(image_bytes):
    """兼容原有函数名，实际使用当前配置的模型。"""
    return ask_ai_with_image(image_bytes)


# ------------------ 键盘监听 ------------------
def on_press(key):
    global last_trigger_at
    try:
        if hasattr(key, 'char') and key.char == '5':
            now = time.time()
            if now - last_trigger_at >= 1.0:  # 1秒防抖
                last_trigger_at = now
                log_info(f"触发截图，范围: left={args.left}, top={args.top}, width={args.width}, height={args.height}")
                Thread(target=on_trigger, daemon=True).start()
    except AttributeError:
        pass


def start_keyboard_listener():
    from pynput import keyboard

    listener = keyboard.Listener(on_press=on_press)
    listener.start()
    log_info("全局热键已注册：按下 '5' 触发（含 1s 防抖）")
    return listener


# ------------------ 触发流程 ------------------
def on_trigger():
    global latest
    if not trigger_lock.acquire(blocking=False):
        log_info("上一条请求尚未结束，跳过重复触发")
        return None
    record = None
    img_bytes = None
    capture_started = None
    try:
        region = (args.left, args.top, args.width, args.height) if args else get_settings().region
        source_image = getattr(args, "image", None)
        record = RecognitionRecord(get_settings(), region=region, source="file" if source_image else "screen")
        capture_started = time.perf_counter()
        img_bytes, capture_ms = capture_region(*region, source_image=source_image)
        record.data["durations"]["captureMs"] = capture_ms
        answer, infer_ms = ask_ai_with_image(img_bytes, record=record)

        item = {
            "id": len(history) + 1,
            "capturedAt": record.data["startedAt"],
            "requestId": record.request_id,
            "recordPath": str(record.path),
            "imageBase64": base64.b64encode(img_bytes).decode('utf-8'),
            "answer": answer,
            "error": False,
            "durations": dict(record.data["durations"]),
        }
        latest = item
    except Exception as e:
        request_id = record.request_id if record else "unassigned"
        if record is None or record.data["status"] != "failed":
            log_error(f"[{request_id}] 触发流程失败: {e}", exc_info=True)
            if record is not None:
                if capture_started is not None and "captureMs" not in record.data["durations"]:
                    record.data["durations"]["captureMs"] = int((time.perf_counter() - capture_started) * 1000)
                try:
                    record.finish(error=e)
                except OSError:
                    log_error(f"[{request_id}] 识别记录写入失败：{record.path}", exc_info=True)
        latest = {
            "id": len(history) + 1,
            "capturedAt": record.data["startedAt"] if record else utc_now(),
            "requestId": request_id,
            "recordPath": str(record.path) if record else None,
            "imageBase64": base64.b64encode(img_bytes).decode("ascii") if img_bytes is not None else None,
            "answer": f"发生错误：{redact_text(e)}",
            "error": True,
            "durations": dict(record.data["durations"]) if record else {},
        }
    finally:
        if latest is not None:
            history.append({key: value for key, value in latest.items() if key != "imageBase64"})
        trigger_lock.release()
    return latest


# ------------------ Web 服务 ------------------
class RequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *values):
        # 自动刷新产生的访问记录只在 DEBUG 输出，避免淹没识别日志。
        logger.debug("HTTP %s %s", self.address_string(), format % values)

    def log_error(self, format, *values):
        logger.error("HTTP %s %s", self.address_string(), format % values)

    def do_GET(self):
        if self.path != '/':
            self.send_response(404)
            self.end_headers()
            return

        if latest and latest["imageBase64"]:
            img_html = f'<img class="img" src="data:image/png;base64,{latest["imageBase64"]}" alt="capture"/>'
        else:
            img_html = '<div class="muted">尚未触发识别，请按 5 键</div>'
        answer_text = escape(latest["answer"] or "(无回答)") if latest else ''
        durations = latest.get("durations", {}) if latest else {}
        duration_text = f"截图 {durations.get('captureMs', 0)}ms · 模型 {durations.get('inferMs', 0)}ms" if durations else ''

        html = f'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <meta http-equiv="refresh" content="1"/>
  <title>视觉问答 - 最新一次</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 24px; line-height: 1.6; }}
    .wrap {{ max-width: 960px; margin: 0 auto; }}
    .card {{ border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px; box-shadow: 0 1px 2px rgba(0,0,0,0.04); }}
    .img {{ max-width: 100%; height: auto; border: 1px solid #ddd; border-radius: 4px; }}
    .answer {{ white-space: pre-wrap; margin-top: 12px; padding: 12px; background:#fafafa; border-radius:6px; }}
    .muted {{ color: #6b7280; }}
  </style>
</head>
<body>
  <div class="wrap">
    <h2>最新一次识别结果</h2>
    {img_html}
    <div class="card answer">{answer_text}</div>
    <div class="muted">{latest['capturedAt'] if latest else ''}</div>
    <div class="muted">{duration_text}</div>
    <div class="muted">{escape('请求编号：' + latest.get('requestId', '')) if latest else ''}</div>
  </div>
</body>
</html>'''

        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(html.encode('utf-8'))


def start_server():
    port = get_settings().port
    server = HTTPServer(('0.0.0.0', port), RequestHandler)
    log_info(f"服务已启动：http://0.0.0.0:{port} （局域网可通过本机IP访问）")
    server.serve_forever()


# ------------------ 主函数 ------------------
def main():
    parser = argparse.ArgumentParser(description="视觉问答系统")
    parser.add_argument('--env', help='配置文件；默认优先读取程序目录的 .env2，其次 .env')
    parser.add_argument('--left', type=int, help='截图区域左上角 X 坐标 (px)')
    parser.add_argument('--top', type=int, help='截图区域左上角 Y 坐标 (px)')
    parser.add_argument('--width', type=int, help='截图宽度 (px)')
    parser.add_argument('--height', type=int, help='截图高度 (px)')
    parser.add_argument('--image', help='用本地图片模拟屏幕；不指定区域时使用整张图片')
    parser.add_argument('--once', action='store_true', help='立即识别一次并退出，不监听热键或启动网页')
    parser.add_argument('--capture-only', metavar='PNG', help='仅保存截图区域到 PNG，不调用 API')

    global args
    args = parser.parse_args()

    try:
        config = configure(args.env)
        defaults = config.region
        if args.image and all(getattr(args, name) is None for name in ("left", "top", "width", "height")):
            with Image.open(args.image) as source:
                defaults = (0, 0, source.width, source.height)
        for name, default in zip(("left", "top", "width", "height"), defaults):
            if getattr(args, name) is None:
                setattr(args, name, default)
        validate_region(args.left, args.top, args.width, args.height)
        log_info(f"配置：{config.env_file}；模型：{config.model}；接口：{config.api_style}")
        log_info(f"截图与识别记录：{config.data_dir / 'requests'}；运行日志：{config.data_dir / 'logs' / 'app.log'}")
        if args.capture_only:
            image_bytes, _ = capture_region(args.left, args.top, args.width, args.height, source_image=args.image)
            Path(args.capture_only).write_bytes(image_bytes)
            log_info(f"截图已保存：{args.capture_only}")
            return 0
        get_api_client()
    except Exception as e:
        log_error(f"启动失败：{e}", exc_info=True)
        print(f"[ERROR] 启动失败：{redact_text(e)}", file=sys.stderr)
        return 1

    if args.once:
        result = on_trigger()
        print(result["answer"])
        return 1 if result["error"] else 0

    # 启动 Web 服务（在主线程或新线程）
    Thread(target=start_server, daemon=True).start()

    # 启动键盘监听
    start_keyboard_listener()

    log_info("程序已启动，等待按键触发...")
    try:
        # 保持主线程运行
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log_info("程序已退出")
        return 0


if __name__ == '__main__':
    sys.exit(main())
