# -*- coding: utf-8 -*-
"""
Python 版本的视觉问答系统
功能：按 5 键 → 截图 → 调用 AI → 显示结果
"""

import argparse
import base64
import json
import os
import sys
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from io import BytesIO
from threading import Thread

import pyautogui
import requests
from PIL import Image
from pynput import keyboard
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# ------------------ 配置 ------------------
PORT = 8003
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# 火山引擎 API 配置
VOLC_API_KEY = os.getenv("VOLC_API_KEY") or os.getenv("VOLCENGINE_API_KEY")
VOLC_BASE_URL = os.getenv("VOLC_BASE_URL") or "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
MODEL_NAME = os.getenv("VOLC_MODEL") or "doubao-1-5-vision-pro-250328"
TEMPERATURE = float(os.getenv("VOLC_TEMPERATURE", 0.2))
MAX_TOKENS = os.getenv("VOLC_MAX_TOKENS")
if MAX_TOKENS:
    MAX_TOKENS = int(MAX_TOKENS)

# 全局状态
latest = None
history = []
last_trigger_at = 0
args = None  # 命令行参数


# ------------------ 日志 ------------------
def log_info(msg):
    if LOG_LEVEL in ("INFO", "DEBUG"):
        print(f"[INFO] {msg}")


def log_error(msg):
    print(f"[ERROR] {msg}")


# ------------------ 截图 ------------------
def capture_region(left, top, width, height):
    start_time = time.time()
    try:
        # 使用 pyautogui 截图
        screenshot = pyautogui.screenshot(region=(left, top, width, height))
        buf = BytesIO()
        screenshot.save(buf, format='PNG')
        img_bytes = buf.getvalue()
        duration_ms = int((time.time() - start_time) * 1000)
        log_info(f"截图完成：{len(img_bytes)} bytes，耗时 {duration_ms}ms")
        return img_bytes, duration_ms
    except Exception as e:
        raise RuntimeError(f"截图失败: {e}")


# ------------------ 调用 AI API ------------------
def ask_doubao_with_image(image_bytes):
    if not VOLC_API_KEY:
        raise ValueError("未配置 VOLC_API_KEY 环境变量")

    base64_str = base64.b64encode(image_bytes).decode('utf-8')
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {VOLC_API_KEY}"
    }

    payload = {
        "model": MODEL_NAME,
        "temperature": TEMPERATURE,
        "messages": [
            {"role": "system", "content": "你是一个擅长中文回答的视觉助手。"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "阅读图片中包含的问题，并用中文直接回答这个问题。"},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{base64_str}"
                        }
                    }
                ]
            }
        ]
    }

    if MAX_TOKENS:
        payload["max_tokens"] = MAX_TOKENS

    start_time = time.time()
    try:
        resp = requests.post(VOLC_BASE_URL, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        infer_ms = int((time.time() - start_time) * 1000)
        log_info(f"模型回答完成，耗时 {infer_ms}ms")

        content = data["choices"][0]["message"]["content"]
        return content, infer_ms
    except Exception as e:
        log_error(f"API 调用失败: {e}")
        return f"调用失败: {e}", int((time.time() - start_time) * 1000)


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
    listener = keyboard.Listener(on_press=on_press)
    listener.start()
    log_info("全局热键已注册：按下 '5' 触发（含 1s 防抖）")
    return listener


# ------------------ 触发流程 ------------------
def on_trigger():
    try:
        img_bytes, capture_ms = capture_region(args.left, args.top, args.width, args.height)
        answer, infer_ms = ask_doubao_with_image(img_bytes)

        item = {
            "id": len(history) + 1,
            "capturedAt": datetime.utcnow().isoformat() + "Z",
            "imageBase64": base64.b64encode(img_bytes).decode('utf-8'),
            "answer": answer,
            "durations": {
                "captureMs": capture_ms,
                "inferMs": infer_ms
            }
        }
        history.append(item)
        global latest
        latest = item
    except Exception as e:
        log_error(f"触发流程失败: {e}")
        latest = {
            "id": len(history) + 1,
            "capturedAt": datetime.utcnow().isoformat() + "Z",
            "imageBase64": None,
            "answer": f"发生错误：{e}",
            "durations": {}
        }


# ------------------ Web 服务 ------------------
class RequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != '/':
            self.send_response(404)
            self.end_headers()
            return

        if latest and latest["imageBase64"]:
            img_html = f'<img class="img" src="data:image/png;base64,{latest["imageBase64"]}" alt="capture"/>'
            answer_text = latest["answer"] or "(无回答)"
        else:
            img_html = '<div class="muted">尚未触发识别，请按 5 键</div>'
            answer_text = ''

        html = f'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <meta http-equiv="refresh" content="2"/>
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
  </div>
</body>
</html>'''

        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(html.encode('utf-8'))


def start_server():
    server = HTTPServer(('0.0.0.0', PORT), RequestHandler)
    log_info(f"服务已启动：http://0.0.0.0:{PORT} （局域网可通过本机IP访问）")
    server.serve_forever()


# ------------------ 主函数 ------------------
def main():
    parser = argparse.ArgumentParser(description="视觉问答系统")
    parser.add_argument('--left', type=int, default=200, help='截图区域左上角 X 坐标 (px)，默认值 200')
    parser.add_argument('--top', type=int, default=200, help='截图区域左上角 Y 坐标 (px)，默认值 200')
    parser.add_argument('--width', type=int, default=1200, help='截图宽度 (px)，默认值 1200')
    parser.add_argument('--height', type=int, default=800, help='截图高度 (px)，默认值 800')

    global args
    args = parser.parse_args()

    # 验证参数
    if any(v < 0 for v in [args.left, args.top, args.width, args.height]):
        log_error("left, top, width, height 必须为非负整数")
        sys.exit(1)

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
        sys.exit(0)


if __name__ == '__main__':
    main()