"""
app/modules/aria2/__init__.py — Aria2 下载器模块

遵循 MoviePilot _DownloaderBase 接口规范，
与 QbittorrentModule / TransmissionModule 保持完全相同的方法签名。
"""
from pathlib import Path
from typing import Set, Tuple, Optional, Union, List, Dict

from torrentool.torrent import Torrent

from app import schemas
from app.core.cache import FileCache
from app.core.config import settings
from app.core.metainfo import MetaInfo
from app.log import logger
from app.modules import _ModuleBase, _DownloaderBase
from app.modules.aria2.aria2 import Aria2
from app.schemas import TransferTorrent, DownloadingTorrent
from app.schemas.types import TorrentStatus, ModuleType, DownloaderType
from app.utils.string import StringUtils


class Aria2Module(_ModuleBase, _DownloaderBase[Aria2]):
    """
    Aria2 下载器模块
    """

    def init_module(self) -> None:
        super().init_service(
            service_name=Aria2.__name__.lower(),   # "aria2"
            service_type=Aria2
        )

    @staticmethod
    def get_name() -> str:
        return "Aria2"

    @staticmethod
    def get_type() -> ModuleType:
        return ModuleType.Downloader

    @staticmethod
    def get_subtype() -> DownloaderType:
        return DownloaderType.Aria2

    @staticmethod
    def get_priority() -> int:
        return 3

    def stop(self):
        pass

    def test(self) -> Optional[Tuple[bool, str]]:
        """测试模块连接性"""
        if not self.get_instances():
            return None
        for name, server in self.get_instances().items():
            version = server.get_version()
            if not version:
                return False, f"无法连接 Aria2 下载器：{name}"
        return True, ""

    def init_setting(self) -> Tuple[str, Union[str, bool]]:
        pass

    def scheduler_job(self) -> None:
        """定时任务（aria2 无状态，空实现）"""
        pass

    # ──────────────────────────────────────────────────────────────────────────
    # 下载
    # ──────────────────────────────────────────────────────────────────────────

    def download(self,
                 content: Union[Path, str, bytes],
                 download_dir: Path,
                 cookie: str,
                 episodes: Set[int] = None,
                 category: Optional[str] = None,
                 label: Optional[str] = None,
                 downloader: Optional[str] = None
                 ) -> Optional[Tuple[Optional[str], Optional[str], Optional[str], str]]:
        """
        添加下载任务。
        :param content:      种子文件路径 / 磁力链接 / 种子内容 bytes
        :param download_dir: 下载目录
        :param cookie:       站点 Cookie（通过 aria2 header 选项传入）
        :param episodes:     需要下载的集数（aria2 不支持选文件，忽略此参数）
        :param category:     分类（aria2 不支持，忽略）
        :param label:        标签（aria2 不支持，忽略）
        :param downloader:   指定下载器实例名称
        :return: (下载器名称, GID, 布局, 错误信息)
        """

        def __get_torrent_content() -> Tuple[Optional[Torrent], Optional[Union[str, bytes]]]:
            tc, ti = None, None
            try:
                if isinstance(content, Path):
                    if content.exists():
                        tc = content.read_bytes()
                    else:
                        tc = FileCache().get(content.as_posix(), region="torrents")
                else:
                    tc = content
                if tc and not StringUtils.is_magnet_link(tc):
                    try:
                        ti = Torrent.from_string(tc)
                    except Exception:
                        pass
                return ti, tc
            except Exception as e:
                logger.error(f"Aria2 读取种子失败：{e}")
                return None, None

        if not content:
            return None, None, None, "下载内容为空"

        torrent_from_file, raw_content = __get_torrent_content()
        is_magnet = (isinstance(raw_content, str) and raw_content.startswith("magnet:")) or \
                    (isinstance(raw_content, bytes) and raw_content.startswith(b"magnet:"))

        if not torrent_from_file and not is_magnet:
            return None, None, None, "添加种子任务失败：无法读取种子文件"

        server: Aria2 = self.get_instance(downloader)
        if not server:
            return None, None, None, "未找到可用的 Aria2 下载器"

        # 添加任务
        gid = server.add_torrent(
            content=raw_content,
            download_dir=self.normalize_path(download_dir, downloader),
            cookie=cookie,
        )

        # aria2 始终使用原始布局
        torrent_layout = "Original"

        if not gid:
            return None, None, None, f"Aria2 添加任务失败：{raw_content}"

        logger.info(f"Aria2 添加任务成功，GID={gid}")
        return (
            downloader or self.get_default_config_name(),
            gid,
            torrent_layout,
            "添加下载任务成功"
        )

    # ──────────────────────────────────────────────────────────────────────────
    # 列出种子
    # ──────────────────────────────────────────────────────────────────────────

    def list_torrents(self,
                      status: TorrentStatus = None,
                      hashs: Union[list, str] = None,
                      downloader: Optional[str] = None
                      ) -> Optional[List[Union[TransferTorrent, DownloadingTorrent]]]:
        """获取下载器种子列表"""
        if downloader:
            server: Aria2 = self.get_instance(downloader)
            if not server:
                return None
            servers = {downloader: server}
        else:
            servers: Dict[str, Aria2] = self.get_instances()

        ret_torrents = []

        if hashs:
            for name, server in servers.items():
                torrents, _ = server.get_torrents(ids=hashs)
                try:
                    for t in torrents:
                        save_path = Aria2._torrent_save_path(t)
                        torrent_name = Aria2._torrent_name(t)
                        torrent_hash = Aria2._torrent_hash(t)
                        total = int(t.get("totalLength", 0))
                        completed = int(t.get("completedLength", 0))
                        progress = (completed / total * 100) if total else 0
                        ret_torrents.append(TransferTorrent(
                            downloader=name,
                            title=torrent_name,
                            path=Path(save_path) / torrent_name if save_path else Path(torrent_name),
                            hash=torrent_hash,
                            size=total,
                            tags="",
                            progress=progress,
                            state="paused" if t.get("status") == "paused" else "downloading",
                        ))
                finally:
                    torrents.clear()
                    del torrents

        elif status == TorrentStatus.TRANSFER:
            for name, server in servers.items():
                torrents = server.get_completed_torrents() or []
                try:
                    for t in torrents:
                        save_path = Aria2._torrent_save_path(t)
                        torrent_name = Aria2._torrent_name(t)
                        torrent_hash = Aria2._torrent_hash(t)
                        if not save_path:
                            logger.debug(f"Aria2 未获取到 {torrent_name} 下载路径")
                            continue
                        ret_torrents.append(TransferTorrent(
                            downloader=name,
                            title=torrent_name,
                            path=Path(save_path) / torrent_name,
                            hash=torrent_hash,
                            size=int(t.get("totalLength", 0)),
                            tags="",
                            progress=100.0,
                        ))
                finally:
                    torrents.clear()
                    del torrents

        elif status == TorrentStatus.DOWNLOADING:
            for name, server in servers.items():
                torrents = server.get_downloading_torrents() or []
                try:
                    for t in torrents:
                        torrent_name = Aria2._torrent_name(t)
                        torrent_hash = Aria2._torrent_hash(t)
                        meta = MetaInfo(torrent_name)
                        total = int(t.get("totalLength", 0))
                        completed = int(t.get("completedLength", 0))
                        progress = (completed / total * 100) if total else 0
                        dlspeed = int(t.get("downloadSpeed", 0))
                        upspeed = int(t.get("uploadSpeed", 0))
                        left_bytes = total - completed
                        left_time = StringUtils.str_secends(left_bytes / dlspeed) if dlspeed > 0 else ""
                        ret_torrents.append(DownloadingTorrent(
                            downloader=name,
                            hash=torrent_hash,
                            title=torrent_name,
                            name=meta.name,
                            year=meta.year,
                            season_episode=meta.season_episode,
                            progress=progress,
                            size=total,
                            state="paused" if t.get("status") == "paused" else "downloading",
                            dlspeed=StringUtils.str_filesize(dlspeed),
                            upspeed=StringUtils.str_filesize(upspeed),
                            tags="",
                            left_time=left_time,
                        ))
                finally:
                    torrents.clear()
                    del torrents
        else:
            return None

        return ret_torrents  # noqa

    # ──────────────────────────────────────────────────────────────────────────
    # 操作接口
    # ──────────────────────────────────────────────────────────────────────────

    def transfer_completed(self, hashs: str, downloader: Optional[str] = None) -> None:
        """
        转移完成后处理。
        aria2 不支持标签，此处仅记录日志。
        """
        logger.info(f"Aria2 任务 {hashs} 已整理完成")
        return None

    def remove_torrents(self,
                        hashs: Union[str, list],
                        delete_file: Optional[bool] = True,
                        downloader: Optional[str] = None) -> Optional[bool]:
        """删除任务"""
        server: Aria2 = self.get_instance(downloader)
        if not server:
            return None
        return server.delete_torrents(delete_file=delete_file, ids=hashs)

    def set_torrents_tag(self,
                         hashs: Union[str, list],
                         tags: list,
                         downloader: Optional[str] = None) -> Optional[bool]:
        """设置种子标签（aria2 不支持，接口兼容返回 True）"""
        return True

    def start_torrents(self,
                       hashs: Union[list, str],
                       downloader: Optional[str] = None) -> Optional[bool]:
        """继续下载"""
        server: Aria2 = self.get_instance(downloader)
        if not server:
            return None
        return server.start_torrents(ids=hashs)

    def stop_torrents(self,
                      hashs: Union[list, str],
                      downloader: Optional[str] = None) -> Optional[bool]:
        """暂停下载"""
        server: Aria2 = self.get_instance(downloader)
        if not server:
            return None
        return server.stop_torrents(ids=hashs)

    def torrent_files(self,
                      tid: str,
                      downloader: Optional[str] = None) -> Optional[List[dict]]:
        """获取种子文件列表"""
        server: Aria2 = self.get_instance(downloader)
        if not server:
            return None
        return server.get_files(tid=tid)

    def downloader_info(self,
                        downloader: Optional[str] = None
                        ) -> Optional[List[schemas.DownloaderInfo]]:
        """下载器传输速率信息"""
        if downloader:
            server: Aria2 = self.get_instance(downloader)
            if not server:
                return None
            server_list = [server]
        else:
            server_list = list(self.get_instances().values())

        ret_info = []
        for server in server_list:
            info = server.transfer_info()
            if not info:
                continue
            ret_info.append(schemas.DownloaderInfo(
                download_speed=info.get("dl_info_speed", 0),
                upload_speed=info.get("up_info_speed", 0),
                download_size=info.get("dl_info_data", 0),
                upload_size=info.get("up_info_data", 0),
            ))
        return ret_info
