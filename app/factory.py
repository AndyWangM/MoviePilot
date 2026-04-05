from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.startup.lifecycle import lifespan
from app.utils.system import SystemUtils


def create_app() -> FastAPI:
    """
    创建并配置 FastAPI 应用实例。
    """
    _app = FastAPI(
        title=settings.PROJECT_NAME,
        openapi_url=f"{settings.API_V1_STR}/openapi.json",
        lifespan=lifespan
    )

    # 配置 CORS 中间件
    _app.add_middleware(
        CORSMiddleware,  # noqa
        allow_origins=settings.ALLOWED_HOSTS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    return _app


def mount_frontend(app: FastAPI):
    """
    frozen（EXE）模式下托管前端静态文件。
    必须在 API 路由注册完成之后调用，否则 StaticFiles("/") 会拦截所有请求。
    """
    if SystemUtils.is_frozen() and SystemUtils.is_windows():
        import sys
        import pathlib
        if hasattr(sys, '_MEIPASS'):
            frontend_path = pathlib.Path(sys._MEIPASS) / "public"
        else:
            frontend_path = pathlib.Path(sys.executable).parent / "public"
        if frontend_path.exists():
            app.mount("/", StaticFiles(directory=str(frontend_path), html=True), name="frontend")


# 创建 FastAPI 应用实例
app = create_app()
