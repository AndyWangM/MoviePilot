"""
tests/test_aria2.py

Aria2 下载器模块单元测试
- 验证 Aria2 客户端 JSON-RPC 调用（mock HTTP）
- 验证 Aria2Module 与 _DownloaderBase 接口兼容性
- 验证 DownloaderType.Aria2 枚举值
"""
import base64
import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, call


# ──────────────────────────────────────────────────────────────────────────────
# 辅助：构造 mock RPC 响应
# ──────────────────────────────────────────────────────────────────────────────

def _rpc_resp(result):
    m = MagicMock()
    m.json.return_value = {"jsonrpc": "2.0", "id": "1", "result": result}
    return m


def _rpc_err(code, msg):
    m = MagicMock()
    m.json.return_value = {"jsonrpc": "2.0", "id": "1", "error": {"code": code, "message": msg}}
    return m


# 模拟 aria2 种子状态 dict
_ACTIVE_TORRENT = {
    "gid": "abc123",
    "status": "active",
    "totalLength": "1073741824",   # 1 GB
    "completedLength": "536870912",  # 512 MB
    "downloadSpeed": "10485760",    # 10 MB/s
    "uploadSpeed": "1048576",       # 1 MB/s
    "dir": "/downloads",
    "bittorrent": {"info": {"name": "Test.Movie.2024.1080p"}},
    "infoHash": "ABCDEF1234567890",
    "files": [{"path": "/downloads/Test.Movie.2024.1080p/movie.mkv", "length": "1073741824",
               "completedLength": "536870912", "selected": "true", "index": "1"}],
}

_COMPLETE_TORRENT = {
    "gid": "def456",
    "status": "complete",
    "totalLength": "524288000",    # 500 MB
    "completedLength": "524288000",
    "downloadSpeed": "0",
    "uploadSpeed": "102400",
    "dir": "/downloads",
    "bittorrent": {"info": {"name": "Test.TV.S01E01.720p"}},
    "infoHash": "FEDCBA0987654321",
    "files": [{"path": "/downloads/Test.TV.S01E01.720p/ep01.mkv", "length": "524288000",
               "completedLength": "524288000", "selected": "true", "index": "1"}],
}


class TestDownloaderTypeAria2(unittest.TestCase):
    """验证 DownloaderType 枚举包含 Aria2。"""

    def test_aria2_in_downloader_type(self):
        from app.schemas.types import DownloaderType
        self.assertTrue(hasattr(DownloaderType, "Aria2"),
                        "DownloaderType 缺少 Aria2 枚举值")
        self.assertEqual(DownloaderType.Aria2.value, "Aria2")


class TestAria2ClientInit(unittest.TestCase):
    """验证 Aria2 客户端初始化。"""

    def _make_client(self, **kwargs):
        from app.modules.aria2.aria2 import Aria2
        return Aria2(**kwargs)

    def test_init_with_host_and_port(self):
        c = self._make_client(host="localhost", port=6800, secret="mysecret")
        self.assertIsNotNone(c._rpc_url)
        self.assertIn("6800", c._rpc_url)
        self.assertIn("jsonrpc", c._rpc_url)

    def test_init_auto_prefix_http(self):
        c = self._make_client(host="192.168.1.100", port=6800)
        self.assertTrue(c._rpc_url.startswith("http://"))

    def test_init_with_http_prefix(self):
        c = self._make_client(host="http://192.168.1.100", port=6800)
        self.assertTrue(c._rpc_url.startswith("http://"))
        # 不会双重 http://
        self.assertNotIn("http://http://", c._rpc_url)

    def test_init_no_host(self):
        from app.modules.aria2.aria2 import Aria2
        c = Aria2(host=None, port=6800)
        self.assertIsNone(c._rpc_url)

    def test_secret_empty_string(self):
        c = self._make_client(host="localhost", port=6800)
        self.assertEqual(c._secret, "")


class TestAria2ClientRPC(unittest.TestCase):
    """验证 Aria2 客户端 JSON-RPC 调用行为（mock HTTP）。"""

    def setUp(self):
        from app.modules.aria2.aria2 import Aria2
        self.client = Aria2(host="localhost", port=6800, secret="test_secret")

    def _patch_rpc(self, result):
        """Patch RequestUtils.post_res 返回指定 result。"""
        return patch("app.utils.http.RequestUtils",
                     return_value=MagicMock(post_res=MagicMock(return_value=_rpc_resp(result))))

    # ── 连接测试 ───────────────────────────────────────────────────────────────

    def test_get_version_success(self):
        with self._patch_rpc({"version": "1.36.0", "enabledFeatures": []}):
            v = self.client.get_version()
        self.assertEqual(v, "1.36.0")

    def test_get_version_fail_returns_none(self):
        with patch("app.utils.http.RequestUtils",
                   return_value=MagicMock(post_res=MagicMock(return_value=None))):
            v = self.client.get_version()
        self.assertIsNone(v)

    # ── 种子查询 ────────────────────────────────────────────────────────────────

    def test_get_torrents_by_id(self):
        with self._patch_rpc(_ACTIVE_TORRENT):
            torrents, error = self.client.get_torrents(ids="abc123")
        self.assertFalse(error)
        self.assertEqual(len(torrents), 1)
        self.assertEqual(torrents[0]["gid"], "abc123")

    def test_get_completed_torrents(self):
        # tellActive / tellWaiting 返回 [], tellStopped 返回完成种子
        def side_effect(url, data=None, **kwargs):
            payload = json.loads(data)
            method = payload["method"]
            if method == "aria2.tellActive":
                return _rpc_resp([])
            elif method == "aria2.tellWaiting":
                return _rpc_resp([])
            elif method == "aria2.tellStopped":
                return _rpc_resp([_COMPLETE_TORRENT])
            return _rpc_resp([])

        mock_ru = MagicMock()
        mock_ru.post_res.side_effect = lambda url, data: side_effect(url, data)
        with patch("app.utils.http.RequestUtils", return_value=mock_ru):
            torrents = self.client.get_completed_torrents()
        self.assertIsNotNone(torrents)
        self.assertEqual(len(torrents), 1)
        self.assertEqual(torrents[0]["status"], "complete")

    def test_get_downloading_torrents(self):
        def side_effect(url, data=None, **kwargs):
            payload = json.loads(data)
            method = payload["method"]
            if method == "aria2.tellActive":
                return _rpc_resp([_ACTIVE_TORRENT])
            elif method == "aria2.tellWaiting":
                return _rpc_resp([])
            elif method == "aria2.tellStopped":
                return _rpc_resp([])
            return _rpc_resp([])

        mock_ru = MagicMock()
        mock_ru.post_res.side_effect = lambda url, data: side_effect(url, data)
        with patch("app.utils.http.RequestUtils", return_value=mock_ru):
            torrents = self.client.get_downloading_torrents()
        self.assertIsNotNone(torrents)
        self.assertEqual(len(torrents), 1)
        self.assertEqual(torrents[0]["status"], "active")

    # ── 添加任务 ────────────────────────────────────────────────────────────────

    def test_add_torrent_magnet(self):
        with self._patch_rpc("abc123"):
            gid = self.client.add_torrent(
                content="magnet:?xt=urn:btih:ABC&dn=test",
                download_dir="/downloads"
            )
        self.assertEqual(gid, "abc123")

    def test_add_torrent_bytes(self):
        fake_torrent = b"d8:announce..."
        with self._patch_rpc("xyz789"):
            gid = self.client.add_torrent(
                content=fake_torrent,
                download_dir="/downloads"
            )
        self.assertEqual(gid, "xyz789")

    def test_add_torrent_bytes_is_base64_encoded(self):
        """验证 bytes 内容被 base64 编码后发送给 aria2.addTorrent。"""
        fake_torrent = b"fake torrent bytes"
        expected_b64 = base64.b64encode(fake_torrent).decode("ascii")

        captured_payload = {}

        def capture(url, data):
            captured_payload.update(json.loads(data))
            return _rpc_resp("gid001")

        mock_ru = MagicMock()
        mock_ru.post_res.side_effect = capture
        with patch("app.utils.http.RequestUtils", return_value=mock_ru):
            self.client.add_torrent(content=fake_torrent, download_dir="/dl")

        self.assertEqual(captured_payload.get("method"), "aria2.addTorrent")
        # params[1] 是 base64 编码的种子
        self.assertEqual(captured_payload["params"][1], expected_b64)

    def test_add_torrent_includes_cookie_in_header(self):
        """验证 Cookie 通过 options.header 传递。"""
        captured_payload = {}

        def capture(url, data):
            captured_payload.update(json.loads(data))
            return _rpc_resp("gid002")

        mock_ru = MagicMock()
        mock_ru.post_res.side_effect = capture
        with patch("app.utils.http.RequestUtils", return_value=mock_ru):
            self.client.add_torrent(
                content="magnet:?xt=urn:btih:TEST",
                download_dir="/dl",
                cookie="session=abc123"
            )
        # options 是 params[-1]（最后一个参数，排除 token）
        options = captured_payload["params"][-1]
        self.assertIn("header", options)
        self.assertIn("Cookie: session=abc123", options["header"])

    def test_add_torrent_returns_none_on_rpc_error(self):
        with patch("app.utils.http.RequestUtils",
                   return_value=MagicMock(post_res=MagicMock(return_value=_rpc_err(-32600, "Invalid")))):
            gid = self.client.add_torrent(content="magnet:?xt=urn:btih:TEST")
        self.assertIsNone(gid)

    # ── 控制 ────────────────────────────────────────────────────────────────────

    def test_start_torrents(self):
        with self._patch_rpc("abc123"):
            result = self.client.start_torrents("abc123")
        self.assertTrue(result)

    def test_stop_torrents(self):
        with self._patch_rpc("abc123"):
            result = self.client.stop_torrents("abc123")
        self.assertTrue(result)

    def test_delete_torrents(self):
        with self._patch_rpc("abc123"):
            result = self.client.delete_torrents(delete_file=True, ids="abc123")
        self.assertTrue(result)

    def test_get_files(self):
        files_resp = [
            {"index": "1", "path": "/downloads/test/movie.mkv",
             "length": "1073741824", "completedLength": "1073741824", "selected": "true"}
        ]
        with self._patch_rpc(files_resp):
            files = self.client.get_files("abc123")
        self.assertIsNotNone(files)
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0]["path"], "/downloads/test/movie.mkv")

    # ── 速度限制 ─────────────────────────────────────────────────────────────────

    def test_set_speed_limit(self):
        captured_payload = {}

        def capture(url, data):
            captured_payload.update(json.loads(data))
            return _rpc_resp("OK")

        mock_ru = MagicMock()
        mock_ru.post_res.side_effect = capture
        with patch("app.utils.http.RequestUtils", return_value=mock_ru):
            result = self.client.set_speed_limit(download_limit=1024, upload_limit=512)
        self.assertTrue(result)
        options = captured_payload["params"][1]
        self.assertEqual(options["max-overall-download-limit"], "1024K")
        self.assertEqual(options["max-overall-upload-limit"], "512K")

    # ── 传输信息 ─────────────────────────────────────────────────────────────────

    def test_transfer_info(self):
        stat = {
            "downloadSpeed": "5242880",
            "uploadSpeed": "1048576",
            "numActive": "1",
            "numWaiting": "0",
            "numStopped": "10",
        }
        with self._patch_rpc(stat):
            info = self.client.transfer_info()
        self.assertIsNotNone(info)
        self.assertEqual(info["dl_info_speed"], 5242880)
        self.assertEqual(info["up_info_speed"], 1048576)

    # ── 标签兼容性 ────────────────────────────────────────────────────────────────

    def test_set_torrents_tag_always_returns_true(self):
        """aria2 不支持标签，set_torrents_tag 应始终返回 True，无 RPC 调用。"""
        result = self.client.set_torrents_tag("abc123", ["已整理"])
        self.assertTrue(result)

    # ── 辅助方法 ─────────────────────────────────────────────────────────────────

    def test_torrent_name_from_bt_info(self):
        from app.modules.aria2.aria2 import Aria2
        name = Aria2._torrent_name(_ACTIVE_TORRENT)
        self.assertEqual(name, "Test.Movie.2024.1080p")

    def test_torrent_name_from_files(self):
        from app.modules.aria2.aria2 import Aria2
        t = {"gid": "x", "files": [{"path": "/downloads/myfile.mkv"}]}
        name = Aria2._torrent_name(t)
        self.assertEqual(name, "myfile.mkv")

    def test_torrent_hash_prefers_infohash(self):
        from app.modules.aria2.aria2 import Aria2
        h = Aria2._torrent_hash(_ACTIVE_TORRENT)
        self.assertEqual(h, "ABCDEF1234567890")

    def test_torrent_hash_falls_back_to_gid(self):
        from app.modules.aria2.aria2 import Aria2
        t = {"gid": "fallback_gid"}
        h = Aria2._torrent_hash(t)
        self.assertEqual(h, "fallback_gid")

    def test_torrent_save_path(self):
        from app.modules.aria2.aria2 import Aria2
        path = Aria2._torrent_save_path(_ACTIVE_TORRENT)
        self.assertEqual(path, "/downloads")


class TestAria2ModuleInterface(unittest.TestCase):
    """验证 Aria2Module 的接口兼容性（不需要真实 aria2 进程）。"""

    def test_get_name(self):
        from app.modules.aria2 import Aria2Module
        self.assertEqual(Aria2Module.get_name(), "Aria2")

    def test_get_type(self):
        from app.modules.aria2 import Aria2Module
        from app.schemas.types import ModuleType
        self.assertEqual(Aria2Module.get_type(), ModuleType.Downloader)

    def test_get_subtype(self):
        from app.modules.aria2 import Aria2Module
        from app.schemas.types import DownloaderType
        self.assertEqual(Aria2Module.get_subtype(), DownloaderType.Aria2)

    def test_get_priority(self):
        from app.modules.aria2 import Aria2Module
        self.assertEqual(Aria2Module.get_priority(), 3)

    def test_test_returns_none_when_no_instances(self):
        from app.modules.aria2 import Aria2Module
        module = object.__new__(Aria2Module)
        module._instances = {}
        module._service_name = "aria2"
        # get_instances() 返回空 dict → test() 应返回 None
        with patch.object(Aria2Module, "get_instances", return_value={}):
            result = module.test()
        self.assertIsNone(result)

    def test_set_torrents_tag_always_true(self):
        from app.modules.aria2 import Aria2Module
        module = object.__new__(Aria2Module)
        with patch.object(Aria2Module, "get_instance", return_value=MagicMock()):
            result = module.set_torrents_tag(hashs="abc", tags=["已整理"])
        self.assertTrue(result)

    def test_transfer_completed_no_exception(self):
        """transfer_completed 不应抛出异常（标签不支持，只记录日志）。"""
        from app.modules.aria2 import Aria2Module
        module = object.__new__(Aria2Module)
        # 不应抛出异常
        try:
            module.transfer_completed(hashs="abc123")
        except Exception as e:
            self.fail(f"transfer_completed 抛出异常：{e}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
