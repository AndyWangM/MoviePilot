"""
tests/test_adult_content.py

验证 tmdbapi.py 中所有 TMDB 搜索调用都传递了 adult=True 参数，
从而确保搜索结果不受 TMDB 的成人内容过滤限制。
"""
import ast
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, call


# ──────────────────────────────────────────────────────────────────────────────
# 静态分析：AST 扫描 tmdbapi.py 中所有 search.* / async_search.* 调用
# ──────────────────────────────────────────────────────────────────────────────

TMDBAPI_PATH = Path(__file__).parent.parent / "app" / "modules" / "themoviedb" / "tmdbapi.py"

# TMDB search 方法名称（同步 + 异步）
SEARCH_METHODS = {
    "multi", "movies", "tv_shows", "people",
    "async_multi", "async_movies", "async_tv_shows", "async_people",
}


def _find_search_calls_without_adult(source_path: Path):
    """
    通过 AST 找出所有 self.search.<method>(...) 调用，
    返回未传递 adult=True 的行号列表。
    """
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(source_path))
    offenders = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # 匹配 self.search.METHOD(...)
        if not (isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Attribute)
                and isinstance(func.value.value, ast.Name)
                and func.value.value.id == "self"
                and func.value.attr == "search"
                and func.attr in SEARCH_METHODS):
            continue
        # 检查 keyword argument adult=True
        has_adult_true = any(
            kw.arg == "adult"
            and isinstance(kw.value, ast.Constant)
            and kw.value.value is True
            for kw in node.keywords
        )
        if not has_adult_true:
            offenders.append((node.lineno, func.attr))

    return offenders


class TestAdultContentAST(unittest.TestCase):
    """AST 静态验证：tmdbapi.py 中不存在未传 adult=True 的 search 调用。"""

    def test_no_search_calls_without_adult_true(self):
        self.assertTrue(TMDBAPI_PATH.exists(), f"找不到 {TMDBAPI_PATH}")
        offenders = _find_search_calls_without_adult(TMDBAPI_PATH)
        if offenders:
            lines = "\n".join(f"  line {ln}: self.search.{meth}(...) 未传 adult=True"
                              for ln, meth in offenders)
            self.fail(f"以下 TMDB 搜索调用未传 adult=True：\n{lines}")

    def test_adult_true_calls_count_is_reasonable(self):
        """至少应有 8 处 adult=True（涵盖 multi/movies/tv_shows/people 的 sync+async 变体）。"""
        self.assertTrue(TMDBAPI_PATH.exists())
        source = TMDBAPI_PATH.read_text(encoding="utf-8")
        # 简单计数
        count = source.count("adult=True")
        self.assertGreaterEqual(count, 8,
            f"adult=True 出现次数 {count} 少于预期 8，可能有遗漏")


# ──────────────────────────────────────────────────────────────────────────────
# 运行时验证：mock self.search，调用 TmdbApi 方法，确认 adult=True 被传递
# ──────────────────────────────────────────────────────────────────────────────

class TestAdultContentRuntime(unittest.TestCase):
    """运行时 mock 验证 TmdbApi 公开方法传递 adult=True。"""

    def setUp(self):
        # 需要 TMDB_API_KEY 环境变量以便导入不报错；使用假值
        os.environ.setdefault("TMDB_API_KEY", "fake_key_for_test")

    def _make_api(self):
        """构造 TmdbApi 实例并替换 self.search 为 MagicMock。"""
        from app.modules.themoviedb.tmdbapi import TmdbApi
        api = object.__new__(TmdbApi)
        # 注入 mock search 对象
        search_mock = MagicMock()
        search_mock.multi.return_value = []
        search_mock.movies.return_value = []
        search_mock.tv_shows.return_value = []
        search_mock.people.return_value = []
        api.search = search_mock
        return api, search_mock

    def test_search_multiis_passes_adult(self):
        api, mock_search = self._make_api()
        api.search_multiis("test title")
        mock_search.multi.assert_called_once()
        _, kwargs = mock_search.multi.call_args
        self.assertTrue(kwargs.get("adult"), "search_multiis 未传 adult=True")

    def test_search_movies_passes_adult_no_year(self):
        api, mock_search = self._make_api()
        mock_search.movies.return_value = [{"title": "test", "media_type": "movie"}]
        api.search_movies("test", "")
        mock_search.movies.assert_called_once()
        _, kwargs = mock_search.movies.call_args
        self.assertTrue(kwargs.get("adult"), "search_movies(no year) 未传 adult=True")

    def test_search_movies_passes_adult_with_year(self):
        api, mock_search = self._make_api()
        mock_search.movies.return_value = [{"title": "test", "media_type": "movie"}]
        api.search_movies("test", "2024")
        mock_search.movies.assert_called_once()
        _, kwargs = mock_search.movies.call_args
        self.assertTrue(kwargs.get("adult"), "search_movies(with year) 未传 adult=True")

    def test_search_tvs_passes_adult_no_year(self):
        api, mock_search = self._make_api()
        mock_search.tv_shows.return_value = [{"name": "test"}]
        api.search_tvs("test", "")
        mock_search.tv_shows.assert_called_once()
        _, kwargs = mock_search.tv_shows.call_args
        self.assertTrue(kwargs.get("adult"), "search_tvs(no year) 未传 adult=True")

    def test_search_tvs_passes_adult_with_year(self):
        api, mock_search = self._make_api()
        mock_search.tv_shows.return_value = [{"name": "test"}]
        api.search_tvs("test", "2024")
        mock_search.tv_shows.assert_called_once()
        _, kwargs = mock_search.tv_shows.call_args
        self.assertTrue(kwargs.get("adult"), "search_tvs(with year) 未传 adult=True")

    def test_search_persons_passes_adult(self):
        api, mock_search = self._make_api()
        api.search_persons("John Doe")
        mock_search.people.assert_called_once()
        _, kwargs = mock_search.people.call_args
        self.assertTrue(kwargs.get("adult"), "search_persons 未传 adult=True")


if __name__ == "__main__":
    unittest.main(verbosity=2)
