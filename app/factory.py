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

    # frozen（EXE）模式下直接托管前端静态文件，不依赖 nginx
    if SystemUtils.is_frozen() and SystemUtils.is_windows():
        import sys
        import pathlib
        frontend_path = pathlib.Path(sys.executable).parent / "public"
        if frontend_path.exists():
            _app.mount("/", StaticFiles(directory=str(frontend_path), html=True), name="frontend")

    return _app


# 创建 FastAPI 应用实例
app = create_app()
