import importlib.util
import json
import shutil
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE = Path(__file__).resolve().parents[1] / "dandanplay_bridge.py"
SPEC = importlib.util.spec_from_file_location("bridge", MODULE)
bridge = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = bridge
SPEC.loader.exec_module(bridge)


def settings(tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"app_id": "id", "app_secret": "secret"}), encoding="utf-8")
    return bridge.Settings.load(config)


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp_path = Path(self._testMethodName)
        self.tmp_path.mkdir(exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(self.tmp_path, ignore_errors=True))

    def test_signature_uses_path_without_query(self):
        captured = {}

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return None

            def read(self):
                return b'{"success": true}'

        def fake_open(request, timeout):
            captured.update(dict(request.header_items()))
            return Response()

        with patch.object(bridge.time, "time", return_value=1000), patch.object(bridge.urllib.request, "urlopen", fake_open):
            bridge.DandanplayClient(settings(self.tmp_path)).request("GET", "/api/v2/comment/1?withRelated=true")
        material = b"id1000/api/v2/comment/1secret"
        self.assertEqual(captured["X-signature"], bridge.base64.b64encode(bridge.hashlib.sha256(material).digest()).decode())

    def test_parse_and_render_ass(self):
        parsed = bridge.parse_comments(
            {"comments": [{"p": "1.5,1,16711680,25", "m": "hello {world}"}, {"p": "3,5,255", "m": "top"}]},
            100,
        )
        text = bridge.ass_from_comments(parsed, settings(self.tmp_path))
        self.assertIn("Dialogue:", text)
        self.assertIn("\\move(", text)
        self.assertIn("\\an8", text)
        self.assertIn("\\{world\\}", text)

    def test_episode_number_parser(self):
        self.assertEqual(bridge.episode_number_from_text("Show.S02E07.1080p.mkv"), 7)
        self.assertEqual(bridge.episode_number_from_text("作品 第 12 话"), 12)


if __name__ == "__main__":
    unittest.main()
