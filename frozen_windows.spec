# -*- mode: python ; coding: utf-8 -*-
# Windows onefile 专用 spec（含启动 Splash 屏）

def collect_pkg_data(package: str, include_py_files: bool = False, subdir: str = None):
    from pathlib import Path
    from PyInstaller.utils.hooks import get_package_paths, PY_IGNORE_EXTENSIONS
    from PyInstaller.building.datastruct import TOC

    data_toc = TOC()
    if type(package) is not str:
        raise ValueError
    try:
        pkg_base, pkg_dir = get_package_paths(package)
    except ValueError:
        return data_toc
    if subdir:
        pkg_path = Path(pkg_dir) / subdir
    else:
        pkg_path = Path(pkg_dir)
    if not pkg_path.exists():
        return data_toc
    for file in pkg_path.rglob('*'):
        if file.is_file():
            extension = file.suffix
            if not include_py_files and (extension in PY_IGNORE_EXTENSIONS):
                continue
            if extension in ('.pyd', '.so', '.bin'):
                continue
            data_toc.append((str(file.relative_to(pkg_base)), str(file), 'DATA'))
    return data_toc


def collect_local_submodules(package: str):
    import os
    from pathlib import Path
    package_dir = Path(package.replace('.', os.sep))
    submodules = [package]
    if not package_dir.exists():
        return []
    for file in package_dir.rglob('*.py'):
        if file.name == '__init__.py':
            module = f"{file.parent}".replace(os.sep, '.')
        else:
            module = f"{file.parent}.{file.stem}".replace(os.sep, '.')
        if module not in submodules:
            submodules.append(module)
    return submodules


import glob as _glob
from pathlib import Path as _Path

hiddenimports = [
    'passlib.handlers.bcrypt',
    # SQLAlchemy 异步方言（动态导入，PyInstaller 无法自动扫描）
    'aiosqlite',
    'sqlalchemy.dialects.sqlite',
    'sqlalchemy.dialects.sqlite.aiosqlite',
    'asyncpg',
    'sqlalchemy.dialects.postgresql',
    'sqlalchemy.dialects.postgresql.asyncpg',
    'psycopg2',
    # uvicorn 动态加载的组件
    'uvicorn.logging',
    'uvicorn.loops',
    'uvicorn.loops.auto',
    'uvicorn.loops.asyncio',
    'uvicorn.protocols',
    'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.http.h11_impl',
    'uvicorn.protocols.http.httptools_impl',
    'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.protocols.websockets.websockets_impl',
    'uvicorn.lifespan',
    'uvicorn.lifespan.on',
    # fastapi / starlette StaticFiles
    'starlette.staticfiles',
    'starlette.templating',
    'aiofiles',
    # 其他常见动态导入
    'multipart',
    'email.mime.text',
    'email.mime.multipart',
] + collect_local_submodules('app') \
  + collect_local_submodules('app.modules') \
  + collect_local_submodules('app.plugins') \
  + collect_local_submodules('app.workflow') \
  + collect_local_submodules('app.chain') \
  + collect_local_submodules('app.core') \
  + collect_local_submodules('app.helper') \
  + collect_local_submodules('app.api') \
  + collect_local_submodules('app.startup') \
  + collect_local_submodules('app.utils') \
  + collect_local_submodules('app.db') \
  + collect_local_submodules('app.schemas')

block_cipher = None

# binaries: .pyd 文件（格式: src, dest_dir）
helper_pyds = []
for pyd in _glob.glob('app/helper/*.pyd'):
    helper_pyds.append((pyd, 'app/helper'))

# datas: .bin 文件 + app.ico + 各包数据
helper_bin_datas = []
for bin_file in _glob.glob('app/helper/*.bin'):
    dest = str(_Path('app/helper') / _Path(bin_file).name)
    helper_bin_datas.append((bin_file, 'app/helper'))

a = Analysis(
    ['app/main.py'],
    pathex=[],
    binaries=helper_pyds,
    datas=[
        ('app.ico', '.'),
        *helper_bin_datas,
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

# 收集各包数据到 Analysis.datas
a.datas += collect_pkg_data('cf_clearance')
a.datas += collect_pkg_data('zhconv')
a.datas += collect_pkg_data('cn2an')
a.datas += collect_pkg_data('Pinyin2Hanzi')
a.datas += collect_pkg_data('database', include_py_files=True)
a.datas += collect_pkg_data('app.helper')

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# Splash 屏：解压时显示，Python 启动后可通过 pyi_splash 更新文字
splash = Splash(
    'splash.png',
    binaries=a.binaries,
    datas=a.datas,
    text_pos=(10, 390),
    text_size=14,
    text_color='white',
    text_default='正在启动 MoviePilot...',
    minify_script=True,
)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    splash,
    splash.binaries,
    name='MoviePilot',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    console=False,
    icon='app.ico',
    # onefile: 不使用 exclude_binaries，不使用 COLLECT
)
