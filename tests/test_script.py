import base64
import json
import os
import tempfile
import unittest
from io import BytesIO, StringIO
from pathlib import Path
from unittest.mock import patch

import httpx
from openai import APITimeoutError, OpenAI, RateLimitError
from PIL import Image

import script


class VisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.reset_client)
        self.data_dir = Path(self.temp.name) / "data"
        env = patch.dict(os.environ, {"DATA_DIR": str(self.data_dir)}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        script.settings = script.Settings(api_key="test-key", model="test-vision", log_level="ERROR", data_dir=self.data_dir)
        with patch.object(script.sys, "stdout", StringIO()):
            script.setup_logging(script.settings)
        script.args = None
        script.latest = None
        script.history = []
        self.requests = []

    def reset_client(self):
        if script.api_client:
            script.api_client.close()
        script.api_client = None
        for handler in list(script.logger.handlers):
            script.logger.removeHandler(handler)
            handler.close()
        script.settings = None

    def config_file(self, text):
        path = Path(self.temp.name) / ".env"
        path.write_text(text, encoding="utf-8")
        return path

    def image_bytes(self, size=(32, 24)):
        buf = BytesIO()
        Image.new("RGB", size, "white").save(buf, "PNG")
        return buf.getvalue()

    def client(self, response=None, status=200, timeout=False):
        def handler(request):
            self.requests.append(request)
            if timeout:
                raise httpx.ReadTimeout("test timeout", request=request)
            return httpx.Response(status, json=response, headers={"x-request-id": "provider-test-id"})

        if script.api_client:
            script.api_client.close()
        script.api_client = OpenAI(api_key="test-key", base_url="https://example.test/v1", max_retries=0,
                                   http_client=httpx.Client(transport=httpx.MockTransport(handler)))

    def test_generic_configuration_and_environment_override(self):
        path = self.config_file("API_KEY=file-key\nAPI_BASE_URL=https://example.test/v1/chat/completions/\nAPI_MODEL=gemini-3.8-flash-high\n")
        with patch.dict(os.environ, {"API_KEY": "environment-key"}):
            config = script.Settings.from_env(path)
        self.assertEqual(config.api_key, "environment-key")
        self.assertEqual(config.base_url, "https://example.test/v1")
        self.assertEqual(config.api_style, "chat_completions")
        self.assertEqual(config.model, "gemini-3.8-flash-high")
        self.assertEqual((config.max_tokens, config.timeout, config.max_retries), (256, 30, 0))
        self.assertNotIn("environment-key", repr(config))

    def test_default_prefers_env2_and_falls_back_to_env(self):
        root = Path(self.temp.name)
        (root / ".env").write_text("API_MODEL=old\n")
        with patch.object(script, "__file__", str(root / "script.py")):
            self.assertEqual(script.Settings.from_env().model, "old")
            (root / ".env2").write_text("API_MODEL=new\n")
            self.assertEqual(script.Settings.from_env().model, "new")
            self.assertEqual(script.Settings.from_env(root / ".env").model, "old")

    def test_openai_aliases_and_legacy_configuration(self):
        config = script.Settings.from_env(self.config_file("OPENAI_API_KEY=alias-key\nOPENAI_BASE_URL=https://example.test/v1\nOPENAI_MODEL=alias-vision\n"))
        self.assertEqual((config.api_key, config.model, config.api_style), ("alias-key", "alias-vision", "chat_completions"))
        config = script.Settings.from_env(self.config_file("VOLC_API_KEY=legacy-key\nVOLC_MODEL=doubao\nVOLC_MAX_TOKENS=1024\n"))
        self.assertEqual(config.api_style, "responses")
        self.assertEqual(config.base_url, "https://ark.cn-beijing.volces.com/api/v3")
        self.assertEqual((config.model, config.max_tokens), ("doubao", 1024))

    def test_invalid_configuration(self):
        for text in ("API_STYLE=invalid", "API_TOKEN_PARAMETER=invalid", "API_REASONING_EFFORT=invalid", "API_TIMEOUT=0", "API_MAX_TOKENS=-1", "API_MAX_RETRIES=-1", "IMAGE_MAX_SIDE=-1", "LOG_LEVEL=invalid", "LOG_MAX_BYTES=0", "LOG_BACKUP_COUNT=0"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                script.Settings.from_env(self.config_file(text))
        with self.assertRaisesRegex(ValueError, "配置文件不存在"):
            script.Settings.from_env(Path(self.temp.name) / "missing")

    def test_simulated_capture_crops_exact_pixels(self):
        source = Image.new("RGB", (80, 60), "white")
        source.paste("red", (10, 20, 30, 40))
        result, duration = script.simulate_capture_region(source, 10, 20, 20, 20)
        with Image.open(BytesIO(result)) as image:
            self.assertEqual(image.size, (20, 20))
            self.assertEqual(image.getpixel((0, 0)), (255, 0, 0))
            self.assertEqual(image.getpixel((19, 19)), (255, 0, 0))
        self.assertGreaterEqual(duration, 0)
        self.assertEqual(source.size, (80, 60))

    def test_simulated_capture_defaults_and_bounds(self):
        path = Path(self.temp.name) / "source.png"
        path.write_bytes(self.image_bytes())
        result, _ = script.simulate_capture_region(path, left=2, top=4)
        with Image.open(BytesIO(result)) as image:
            self.assertEqual(image.size, (30, 20))
        for region in ((-1, 0, 1, 1), (0, 0, 0, 1), (0, 0, 40, 40)):
            with self.subTest(region=region), self.assertRaises((ValueError, RuntimeError)):
                script.capture_region(*region, source_image=path)

    def test_chat_request_and_plain_text_answer(self):
        self.client({"id": "chat-test", "choices": [{"message": {"role": "assistant", "content": " B "}, "finish_reason": "stop", "index": 0}]})
        script.settings.image_max_side = 16
        answer, duration = script.ask_ai_with_image(self.image_bytes())
        self.assertEqual(answer, "B")
        self.assertGreaterEqual(duration, 0)
        self.assertEqual(self.requests[0].url.path, "/v1/chat/completions")
        body = json.loads(self.requests[0].content)
        self.assertEqual(body["model"], "test-vision")
        self.assertEqual(body["max_tokens"], 256)
        self.assertNotIn("max_output_tokens", body)
        self.assertNotIn("reasoning_effort", body)
        url = body["messages"][0]["content"][1]["image_url"]["url"]
        with Image.open(BytesIO(base64.b64decode(url.split(",", 1)[1]))) as image:
            self.assertEqual(image.size, (16, 12))

    def test_responses_request_and_plain_text_answer(self):
        script.settings.api_style = "responses"
        self.client({"id": "resp-test", "status": "completed", "output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "答案是B", "annotations": []}]}]})
        answer, _ = script.ask_ai_with_image(self.image_bytes())
        self.assertEqual(answer, "答案是B")
        self.assertEqual(self.requests[0].url.path, "/v1/responses")
        body = json.loads(self.requests[0].content)
        self.assertEqual(body["max_output_tokens"], 256)
        self.assertNotIn("max_tokens", body)
        self.assertNotIn("reasoning", body)
        self.assertEqual(body["input"][0]["content"][1]["type"], "input_image")

    def test_reasoning_effort_for_chat(self):
        script.settings = script.Settings.from_env(self.config_file("API_KEY=test-key\nAPI_MODEL=gemini-3.1-flash-lite\nAPI_REASONING_EFFORT=minimal\n"))
        self.client({"choices": [{"message": {"content": "B"}, "index": 0}]})
        script.ask_ai_with_image(self.image_bytes())
        body = json.loads(self.requests[0].content)
        self.assertEqual(body["reasoning_effort"], "minimal")
        self.assertNotIn("reasoning", body)

    def test_reasoning_effort_for_responses(self):
        script.settings.api_style = "responses"
        script.settings.reasoning_effort = "low"
        self.client({"status": "completed", "output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "B", "annotations": []}]}]})
        script.ask_ai_with_image(self.image_bytes())
        body = json.loads(self.requests[0].content)
        self.assertEqual(body["reasoning"], {"effort": "low"})
        self.assertNotIn("reasoning_effort", body)

    def test_optional_parameters_can_be_omitted(self):
        script.settings = script.Settings.from_env(self.config_file("API_KEY=test-key\nAPI_MODEL=test\nAPI_TEMPERATURE=\nAPI_MAX_TOKENS=\nAPI_REASONING_EFFORT=\n"))
        self.client({"choices": [{"message": {"content": "OK"}, "index": 0}]})
        script.ask_ai_with_image(self.image_bytes())
        body = json.loads(self.requests[0].content)
        self.assertNotIn("temperature", body)
        self.assertNotIn("max_tokens", body)
        self.assertNotIn("reasoning_effort", body)

    def test_alternative_token_parameter(self):
        script.settings.token_parameter = "max_completion_tokens"
        self.client({"choices": [{"message": {"content": "OK"}, "index": 0}]})
        script.ask_ai_with_image(self.image_bytes())
        body = json.loads(self.requests[0].content)
        self.assertEqual(body["max_completion_tokens"], 256)
        self.assertNotIn("max_tokens", body)

    def test_empty_answer_is_an_error(self):
        self.client({"choices": [{"message": {"content": None}, "index": 0}]})
        with self.assertRaisesRegex(RuntimeError, "未返回文字答案"):
            script.ask_ai_with_image(self.image_bytes())

    def test_api_errors_do_not_retry(self):
        self.client({"error": {"message": "busy", "type": "rate_limit"}}, status=429)
        with self.assertRaises(RateLimitError):
            script.ask_ai_with_image(self.image_bytes())
        self.assertEqual(len(self.requests), 1)

    def test_request_timeout(self):
        self.client(timeout=True)
        with self.assertRaises(APITimeoutError):
            script.ask_ai_with_image(self.image_bytes())
        self.assertEqual(len(self.requests), 1)

    def test_failed_capture_is_visible_and_releases_lock(self):
        with patch.object(script, "capture_region", side_effect=RuntimeError("test failure")):
            result = script.on_trigger()
        self.assertTrue(result["error"])
        self.assertIn("test failure", result["answer"])
        self.assertFalse(script.trigger_lock.locked())
        record = json.loads(Path(result["recordPath"]).read_text())
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["stage"], "capture")
        self.assertIsNone(record["screenshot"])
        self.assertEqual(record["error"]["type"], "RuntimeError")
        script.latest["answer"] += "<script>alert(1)</script>"
        handler = script.RequestHandler.__new__(script.RequestHandler)
        handler.path = "/"
        handler.wfile = BytesIO()
        with patch.object(handler, "send_response"), patch.object(handler, "send_header"), patch.object(handler, "end_headers"):
            handler.do_GET()
        html = handler.wfile.getvalue().decode()
        self.assertIn("test failure", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<script>", html)

    def test_repeated_trigger_does_not_send_another_request(self):
        script.trigger_lock.acquire()
        try:
            with patch.object(script, "capture_region") as capture:
                self.assertIsNone(script.on_trigger())
                capture.assert_not_called()
        finally:
            script.trigger_lock.release()

    def test_success_archives_original_and_resized_input_with_response_metadata(self):
        script.settings.image_max_side = 16
        self.client({"id": "reply-id", "model": "provider-model", "choices": [{"message": {"content": "B"}, "index": 0, "finish_reason": "stop"}],
                     "usage": {"prompt_tokens": 12, "completion_tokens": 1, "total_tokens": 13}})
        original = self.image_bytes()
        with patch.object(script, "capture_region", return_value=(original, 3)):
            result = script.on_trigger()
        self.assertFalse(result["error"])
        path = Path(result["recordPath"])
        record = json.loads(path.read_text())
        self.assertEqual(record["status"], "completed")
        self.assertEqual(record["answer"], "B")
        self.assertEqual(record["region"], list(script.settings.region))
        self.assertEqual(record["durations"]["captureMs"], 3)
        self.assertGreaterEqual(record["durations"]["totalMs"], record["durations"]["inferMs"])
        self.assertEqual((path.parent / record["screenshot"]["file"]).read_bytes(), original)
        self.assertEqual(record["inputImage"]["width"], 16)
        input_url = json.loads(self.requests[0].content)["messages"][0]["content"][1]["image_url"]["url"]
        self.assertEqual((path.parent / record["inputImage"]["file"]).read_bytes(), base64.b64decode(input_url.split(",", 1)[1]))
        self.assertEqual(record["response"]["usage"]["total_tokens"], 13)
        self.assertEqual(record["response"]["requestId"], "provider-test-id")
        self.assertEqual(record["response"]["finishReason"], "stop")
        self.assertNotIn("test-key", path.read_text())
        self.assertNotIn("imageBase64", script.history[-1])
        self.assertFalse(path.with_suffix(".json.tmp").exists())

    def test_screenshot_is_saved_before_network_request(self):
        def handler(request):
            files = list(self.data_dir.glob("requests/*/*/record.json"))
            self.assertEqual(len(files), 1)
            data = json.loads(files[0].read_text())
            self.assertEqual(data["status"], "requesting")
            self.assertTrue((files[0].parent / data["screenshot"]["file"]).is_file())
            return httpx.Response(200, json={"choices": [{"message": {"content": "B"}, "index": 0}]})

        script.api_client = OpenAI(api_key="test-key", base_url="https://example.test/v1", max_retries=0,
                                   http_client=httpx.Client(transport=httpx.MockTransport(handler)))
        script.ask_ai_with_image(self.image_bytes())

    def test_api_failure_keeps_image_and_redacts_error_and_stack(self):
        error_text = "busy test-key Bearer private-secret data:image/png;base64,QUJDRA=="
        self.client({"error": {"message": error_text, "type": "rate_limit"}}, status=429)
        original = self.image_bytes()
        with patch.object(script, "capture_region", return_value=(original, 2)):
            result = script.on_trigger()
        path = Path(result["recordPath"])
        record = json.loads(path.read_text())
        self.assertTrue(result["error"])
        self.assertEqual(base64.b64decode(result["imageBase64"]), original)
        self.assertEqual((path.parent / "screenshot.png").read_bytes(), original)
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["stage"], "api_request")
        self.assertEqual(record["error"]["httpStatus"], 429)
        self.assertIn("inferMs", record["durations"])
        log = (self.data_dir / "logs" / "app.log").read_text()
        self.assertIn("Traceback", log)
        self.assertIn(record["requestId"], log)
        for text in (log, path.read_text(), result["answer"]):
            self.assertNotIn("test-key", text)
            self.assertNotIn("private-secret", text)
            self.assertNotIn("QUJDRA==", text)
            self.assertIn("[REDACTED]", text)
        self.assertFalse(script.trigger_lock.locked())

    def test_archive_failure_prevents_unrecorded_api_call(self):
        with patch.object(script, "capture_region", return_value=(self.image_bytes(), 1)), \
             patch.object(script.RecognitionRecord, "save_image", side_effect=OSError("disk full")), \
             patch.object(script, "get_api_client") as client:
            result = script.on_trigger()
        client.assert_not_called()
        self.assertTrue(result["error"])
        self.assertIn("disk full", result["answer"])
        self.assertFalse(script.trigger_lock.locked())
        record = json.loads(Path(result["recordPath"]).read_text())
        self.assertEqual(record["stage"], "save_screenshot")

    def test_repeated_requests_never_send_old_context_for_either_api(self):
        script.history.append({"answer": "OLD_HISTORY_MARKER", "imageBase64": "OLD_IMAGE_MARKER"})
        script.latest = {"answer": "OLD_LATEST_MARKER"}
        for style in ("chat_completions", "responses"):
            with self.subTest(style=style):
                script.settings.api_style = style
                response = {"id": "old-provider-response", "choices": [{"message": {"content": "OLD_ANSWER_MARKER"}, "index": 0}],
                            "status": "completed", "output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "OLD_ANSWER_MARKER", "annotations": []}]}]}
                self.client(response)
                script.ask_ai_with_image(self.image_bytes())
                script.ask_ai_with_image(self.image_bytes((40, 30)))
                body = json.loads(self.requests[-1].content)
                messages = body["messages" if style == "chat_completions" else "input"]
                self.assertEqual(len(messages), 1)
                self.assertEqual(messages[0]["role"], "user")
                self.assertEqual(len(messages[0]["content"]), 2)
                self.assertNotIn("previous_response_id", body)
                self.assertNotIn("conversation", body)
                self.assertNotIn("OLD_", self.requests[-1].content.decode())
                self.assertNotIn("old-provider-response", self.requests[-1].content.decode())
        paths = list(self.data_dir.glob("requests/*/*/record.json"))
        self.assertEqual(len(paths), 4)
        self.assertEqual(len({json.loads(path.read_text())["requestId"] for path in paths}), 4)
        self.assertTrue(all(json.loads(path.read_text())["context"]["historyMessages"] == 0 for path in paths))

    def test_logging_rotates_and_reconfiguration_does_not_duplicate_handlers(self):
        script.settings.log_max_bytes = 400
        script.settings.log_backup_count = 2
        script.settings.log_level = "INFO"
        with patch.object(script.sys, "stdout", StringIO()):
            script.setup_logging(script.settings)
            script.setup_logging(script.settings)
        self.assertEqual(len(script.logger.handlers), 2)
        for number in range(25):
            script.log_info(f"entry-{number} test-key " + "x" * 100)
        logs = sorted((self.data_dir / "logs").glob("app.log*"))
        self.assertEqual(len(logs), 3)
        text = "".join(path.read_text() for path in logs)
        self.assertIn("entry-24", text)
        self.assertNotIn("test-key", text)
        self.assertIn("[REDACTED]", text)

    def test_relative_data_path_uses_program_directory(self):
        root = Path(self.temp.name)
        path = self.config_file("DATA_DIR=archives\n")
        with patch.dict(os.environ, {}, clear=True), patch.object(script, "__file__", str(root / "script.py")):
            config = script.Settings.from_env(path)
        self.assertEqual(config.data_dir, (root / "archives").resolve())


if __name__ == "__main__":
    unittest.main()
