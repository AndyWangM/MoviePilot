import multiprocessing
import os
import pathlib
import setproctitle
import signal
import sys
import threading

import uvicorn as uvicorn
from PIL import Image
from uvicorn import Config

from app.factory import app
from app.utils.system import SystemUtils

# frozen 模式：把 stdout/stderr 重定向到日志文件，确保闪退也能看到错误
if SystemUtils.is_frozen():
    _log_dir = pathlib.Path(sys.executable).parent / "config" / "logs"
    _log_dir.mkdir(parents=True, exist_ok=True)
    _crash_log = _log_dir / "startup.log"
    _f = open(_crash_log, "w", encoding="utf-8", buffering=1)
    sys.stdout = _f
    sys.stderr = _f
    print(f"[startup] log -> {_crash_log}", flush=True)

from app.core.config import settings
from app.db.init import init_db, update_db

# 设置进程名
setproctitle.setproctitle(settings.PROJECT_NAME)

# uvicorn服务
Server = uvicorn.Server(Config(app, host=settings.HOST, port=settings.PORT,
                               reload=settings.DEV, workers=multiprocessing.cpu_count() * 2 + 1,
                               timeout_graceful_shutdown=60))


def splash_update(text: str):
    """
    更新 onefile splash 屏文字（仅 frozen + pyi_splash 可用时生效）
    """
    try:
        import pyi_splash  # noqa - 仅 onefile 模式下存在
        pyi_splash.update_text(text)
    except Exception:
        pass


def splash_close():
    """
    关闭 splash 屏
    """
    try:
        import pyi_splash  # noqa
        pyi_splash.close()
    except Exception:
        pass


def start_tray():
    """
    启动托盘图标
    """
    if not SystemUtils.is_frozen():
        return
    if not SystemUtils.is_windows():
        return

    def open_web():
        import webbrowser
        webbrowser.open(f"http://localhost:{settings.PORT}")

    def open_log():
        log_file = pathlib.Path(sys.executable).parent / "config" / "logs" / "startup.log"
        if log_file.exists():
            os.startfile(str(log_file))

    def show_login_info():
        import ctypes
        msg = (
            f"MoviePilot 登录信息\n\n"
            f"地址：http://localhost:{settings.PORT}\n"
            f"用户名：{settings.SUPERUSER}\n"
            f"初始密码：admin\n\n"
            f"（首次登录后请在「设定 → 用户」中修改密码）"
        )
        ctypes.windll.user32.MessageBoxW(0, msg, "MoviePilot 登录信息", 0x40)  # 0x40 = MB_ICONINFORMATION

    def quit_app():
        TrayIcon.stop()
        Server.should_exit = True

    import pystray

    TrayIcon = pystray.Icon(
        settings.PROJECT_NAME,
        icon=Image.open(settings.ROOT_PATH / 'app.ico'),
        menu=pystray.Menu(
            pystray.MenuItem('打开', open_web, default=True),
            pystray.MenuItem('登录信息', show_login_info),
            pystray.MenuItem('查看日志', open_log),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem('退出', quit_app),
        )
    )
    threading.Thread(target=TrayIcon.run, daemon=True).start()

    # 弹出一次登录提示气泡（仅首次启动时显示）
    _first_run_flag = pathlib.Path(sys.executable).parent / "config" / ".initialized"
    if not _first_run_flag.exists():
        def _notify():
            import time
            time.sleep(3)  # 等托盘图标就绪
            try:
                TrayIcon.notify(
                    f"用户名：{settings.SUPERUSER}\n初始密码：admin\n右键托盘图标 → 登录信息",
                    "MoviePilot 首次登录提示"
                )
            except Exception:
                pass
        threading.Thread(target=_notify, daemon=True).start()


def signal_handler(signum, frame):
    print(f"收到信号 {signum}，开始优雅停止服务...")
    Server.should_exit = True


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    splash_update("正在初始化数据库...")
    # 启动托盘
    start_tray()
    # 初始化数据库
    init_db()
    # 更新数据库
    update_db()

    # 写入首次启动标记（在 init_db 之后，确保数据库已初始化）
    if SystemUtils.is_frozen():
        _flag = pathlib.Path(sys.executable).parent / "config" / ".initialized"
        _flag.parent.mkdir(parents=True, exist_ok=True)
        if not _flag.exists():
            _flag.touch()

    splash_update("正在启动服务，请稍候...")
    # splash 在 uvicorn 开始监听后关闭（通过 lifespan startup 事件）
    # 这里先关掉，避免 uvicorn 阻塞时 splash 一直挂着
    splash_close()

    # 启动API服务
    Server.run()
