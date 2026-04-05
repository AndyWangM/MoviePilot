"""
aria2.py — Aria2 下载器客户端

通过 Aria2 JSON-RPC（HTTP）协议与 aria2 进程通信。
RPC 端点: http://<host>:<port>/jsonrpc
认证方式: JSON-RPC 参数 token:<secret>

对外暴露与 Qbittorrent / Transmission 相同的方法签名，
使 Aria2Module 能以相同方式被 _DownloaderBase 驱动。
"""
from __future__ import annotations

import base64
import json
import time
from typing import Any, Dict, List, Optional, Tuple, Union

from app.log import logger
from app.utils.url import UrlUtils


# ──────────────────────────────────────────────────────────────────────────────
# Aria2 RPC 返回状态 → MoviePilot TorrentStatus 映射
# aria2 status: active / waiting / paused / error / complete / removed
# ──────────────────────────────────────────────────────────────────────────────

_ARIA2_ACTIVE_STATES   = {"active"}
_ARIA2_WAITING_STATES  = {"waiting", "paused"}
_ARIA2_DONE_STATES     = {"complete"}
_ARIA2_ERROR_STATES    = {"error", "removed"}


class Aria2:
    """
    Aria2 下载器封装（JSON-RPC over HTTP）。

    初始化参数（对应 DownloaderConf.config）：
      host     - RPC 主机，含或不含协议头均可，如 "localhost" / "http://192.168.1.1"
      port     - RPC 端口，默认 6800
      secret   - RPC 密钥（aria2c --rpc-secret 配置的值）
    """

    _DEFAULT_PORT = 6800
    _RPC_PATH     = "/jsonrpc"

    def __init__(self,
                 host: Optional[str] = None,
                 port: Optional[int] = None,
                 secret: Optional[str] = None,
                 **kwargs):
        self._host   = None
        self._port   = None
        self._secret = secret or ""
        self._rpc_url: Optional[str] = None

        if host and port:
            self._host = host
            self._port = int(port)
        elif host:
            result = UrlUtils.parse_url_params(url=host)
            if result:
                _, h, p, _ = result
                self._host = h
                self._port = p or self._DEFAULT_PORT
            else:
                # 只有 host 无协议
                self._host = host.rstrip("/")
                self._port = self._DEFAULT_PORT
        else:
            logger.error("Aria2 配置不完整：缺少 host")
            return

        # 规范化 host（去掉末尾 /）
        if self._host and not self._host.startswith("http"):
            self._host = "http://" + self._host
        self._host = self._host.rstrip("/")

        self._rpc_url = f"{self._host}:{self._port}{self._RPC_PATH}"
        logger.info(f"Aria2 RPC 端点：{self._rpc_url}")

    # ──────────────────────────────────────────────────────────────────────────
    # 内部 RPC 调用
    # ──────────────────────────────────────────────────────────────────────────

    def _rpc(self, method: str, *params) -> Any:
        """
        发送 JSON-RPC 请求，返回 result 字段值；失败返回 None。
        """
        if not self._rpc_url:
            return None
        token = f"token:{self._secret}"
        payload = {
            "jsonrpc": "2.0",
            "id":      str(int(time.time() * 1000)),
            "method":  f"aria2.{method}",
            "params":  [token, *params],
        }
        try:
            from app.utils.http import RequestUtils
            resp = RequestUtils(
                content_type="application/json",
                timeout=15,
            ).post_res(url=self._rpc_url, data=json.dumps(payload))
            if resp is None:
                logger.error(f"Aria2 RPC 请求无响应：{method}")
                return None
            data = resp.json()
            if "error" in data:
                logger.error(f"Aria2 RPC 错误 [{method}]：{data['error']}")
                return None
            return data.get("result")
        except Exception as e:
            logger.error(f"Aria2 RPC 调用出错 [{method}]：{e}")
            return None

    # ──────────────────────────────────────────────────────────────────────────
    # 连接 / 状态
    # ──────────────────────────────────────────────────────────────────────────

    def is_inactive(self) -> bool:
        """判断是否需要重连（aria2 RPC 是无状态 HTTP，永不需要重连）。"""
        return False

    def reconnect(self):
        """无状态协议，重连为 no-op。"""
        pass

    def get_version(self) -> Optional[str]:
        """获取 aria2 版本，同时用于连接测试。"""
        result = self._rpc("getVersion")
        if result:
            return result.get("version")
        return None

    def transfer_info(self) -> Optional[Dict]:
        """
        获取全局传输速率信息。
        返回格式与其他下载器兼容：
          dl_info_speed  - 当前下载速度 bytes/s
          up_info_speed  - 当前上传速度 bytes/s
          dl_info_data   - 本会话下载总量 bytes
          up_info_data   - 本会话上传总量 bytes
        """
        result = self._rpc("getGlobalStat")
        if not result:
            return None
        return {
            "dl_info_speed": int(result.get("downloadSpeed", 0)),
            "up_info_speed": int(result.get("uploadSpeed", 0)),
            "dl_info_data":  0,   # aria2 全局统计无此字段
            "up_info_data":  0,
        }

    # ──────────────────────────────────────────────────────────────────────────
    # 查询种子
    # ──────────────────────────────────────────────────────────────────────────

    def get_torrents(self,
                     ids: Union[str, list] = None,
                     status: Union[str, list] = None,
                     tags: Union[str, list] = None
                     ) -> Tuple[List[dict], bool]:
        """
        获取种子列表。
        :param ids:    GID 列表或单个 GID
        :param status: "downloading" / "seeding" / "completed" 等
        :param tags:   暂不支持（aria2 无 label）
        :return: (种子列表, 是否出错)
        """
        try:
            if ids:
                gids = [ids] if isinstance(ids, str) else ids
                torrents = []
                for gid in gids:
                    r = self._rpc("tellStatus", gid)
                    if r:
                        torrents.append(r)
                return torrents, False

            # 按状态查询
            active   = self._rpc("tellActive")   or []
            waiting  = self._rpc("tellWaiting", 0, 1000) or []
            stopped  = self._rpc("tellStopped", 0, 1000) or []

            all_torrents = active + waiting + stopped

            if status:
                if isinstance(status, str):
                    status = [status]
                filtered = []
                for t in all_torrents:
                    s = t.get("status", "")
                    if "downloading" in status and s in _ARIA2_ACTIVE_STATES | _ARIA2_WAITING_STATES:
                        filtered.append(t)
                    elif "completed" in status and s in _ARIA2_DONE_STATES:
                        filtered.append(t)
                    elif "seeding" in status and s in _ARIA2_DONE_STATES:
                        filtered.append(t)
                return filtered, False

            return all_torrents, False
        except Exception as e:
            logger.error(f"Aria2 获取种子列表出错：{e}")
            return [], True

    def get_completed_torrents(self,
                               ids: Union[str, list] = None,
                               tags: Union[str, list] = None) -> Optional[List[dict]]:
        """获取已完成的种子。"""
        torrents, error = self.get_torrents(ids=ids, status=["completed"])
        return None if error else torrents

    def get_downloading_torrents(self,
                                 ids: Union[str, list] = None,
                                 tags: Union[str, list] = None) -> Optional[List[dict]]:
        """获取正在下载（active + waiting）的种子。"""
        torrents, error = self.get_torrents(ids=ids, status=["downloading"])
        return None if error else torrents

    # ──────────────────────────────────────────────────────────────────────────
    # 添加任务
    # ──────────────────────────────────────────────────────────────────────────

    def add_torrent(self,
                    content: Union[str, bytes],
                    download_dir: Optional[str] = None,
                    is_paused: Optional[bool] = False,
                    cookie: Optional[str] = None,
                    **kwargs) -> Optional[str]:
        """
        添加下载任务，返回 GID（成功）或 None（失败）。

        :param content:      磁力链/URL（str）或 .torrent 文件内容（bytes）
        :param download_dir: 保存目录
        :param is_paused:    添加后是否暂停（通过 pause 选项）
        :param cookie:       Cookie（通过 header 选项传入）
        """
        options: Dict[str, str] = {}
        if download_dir:
            options["dir"] = str(download_dir)
        if is_paused:
            options["pause"] = "true"
        if cookie:
            options["header"] = [f"Cookie: {cookie}"]

        try:
            if isinstance(content, bytes):
                # .torrent 文件内容
                encoded = base64.b64encode(content).decode("ascii")
                gid = self._rpc("addTorrent", encoded, [], options)
            else:
                # 磁力链 / URL
                content_str = content if isinstance(content, str) else content.decode("utf-8")
                gid = self._rpc("addUri", [content_str], options)
            return gid if isinstance(gid, str) else None
        except Exception as e:
            logger.error(f"Aria2 添加任务出错：{e}")
            return None

    # ──────────────────────────────────────────────────────────────────────────
    # 控制任务
    # ──────────────────────────────────────────────────────────────────────────

    def start_torrents(self, ids: Union[str, list]) -> bool:
        """继续（unpause）下载。"""
        try:
            gids = [ids] if isinstance(ids, str) else ids
            for gid in gids:
                result = self._rpc("unpause", gid)
                if result is None:
                    return False
            return True
        except Exception as e:
            logger.error(f"Aria2 继续下载出错：{e}")
            return False

    def stop_torrents(self, ids: Union[str, list]) -> bool:
        """暂停下载。"""
        try:
            gids = [ids] if isinstance(ids, str) else ids
            for gid in gids:
                result = self._rpc("pause", gid)
                if result is None:
                    return False
            return True
        except Exception as e:
            logger.error(f"Aria2 暂停下载出错：{e}")
            return False

    def delete_torrents(self,
                        delete_file: bool,
                        ids: Union[str, list]) -> bool:
        """
        删除任务。
        aria2 的 remove 只移除任务，不删除文件；
        若需删文件，先 remove 再对已停止任务调用 removeDownloadResult。
        """
        if not ids:
            return False
        try:
            gids = [ids] if isinstance(ids, str) else ids
            for gid in gids:
                # 先尝试 remove（active/waiting）
                r = self._rpc("remove", gid)
                if r is None:
                    # 已经 stopped，用 forceRemove 无效，直接 removeDownloadResult
                    self._rpc("removeDownloadResult", gid)
            return True
        except Exception as e:
            logger.error(f"Aria2 删除任务出错：{e}")
            return False

    # ──────────────────────────────────────────────────────────────────────────
    # 文件列表（aria2 支持种子文件列表）
    # ──────────────────────────────────────────────────────────────────────────

    def get_files(self, tid: str) -> Optional[List[dict]]:
        """
        获取种子文件列表。
        返回 aria2 getFiles 原始结果，每项含 index/path/length/completedLength/selected 字段。
        """
        if not tid:
            return None
        try:
            return self._rpc("getFiles", tid) or []
        except Exception as e:
            logger.error(f"Aria2 获取文件列表出错：{e}")
            return None

    # ──────────────────────────────────────────────────────────────────────────
    # 标签（aria2 原生不支持，保留接口兼容性）
    # ──────────────────────────────────────────────────────────────────────────

    def set_torrents_tag(self, ids: Union[str, list], tags: list) -> bool:
        """
        aria2 不支持标签，此方法为接口兼容性保留，始终返回 True。
        """
        return True

    def set_torrent_tag(self, ids: str, tags: list, org_tags: list = None) -> bool:
        return True

    # ──────────────────────────────────────────────────────────────────────────
    # 速度限制
    # ──────────────────────────────────────────────────────────────────────────

    def set_speed_limit(self,
                        download_limit: Optional[float] = None,
                        upload_limit: Optional[float] = None) -> bool:
        """
        设置全局速度限制。
        :param download_limit: 下载限速 KB/s（0 = 不限）
        :param upload_limit:   上传限速 KB/s（0 = 不限）
        """
        try:
            options = {}
            if download_limit is not None:
                # aria2 使用 bytes/s 或 "K" 后缀
                options["max-overall-download-limit"] = f"{int(download_limit)}K"
            if upload_limit is not None:
                options["max-overall-upload-limit"] = f"{int(upload_limit)}K"
            if options:
                return self._rpc("changeGlobalOption", options) is not None
            return True
        except Exception as e:
            logger.error(f"Aria2 设置速度限制出错：{e}")
            return False

    # ──────────────────────────────────────────────────────────────────────────
    # 辅助方法
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _torrent_name(torrent: dict) -> Optional[str]:
        """从 aria2 种子状态 dict 中提取名称。"""
        # BT 种子
        bt_info = torrent.get("bittorrent", {}).get("info", {})
        if bt_info.get("name"):
            return bt_info["name"]
        # HTTP/磁力（取 files[0].path 的最后一段）
        files = torrent.get("files", [])
        if files:
            path = files[0].get("path", "")
            if path:
                return path.rstrip("/").split("/")[-1]
        return torrent.get("gid", "")

    @staticmethod
    def _torrent_hash(torrent: dict) -> Optional[str]:
        """从 aria2 种子状态 dict 中提取 info-hash（大写 hex）。"""
        return torrent.get("infoHash") or torrent.get("gid")

    @staticmethod
    def _torrent_save_path(torrent: dict) -> str:
        """获取保存目录。"""
        return torrent.get("dir", "")
