# -*- mode: python ; coding: utf-8 -*-
# Windows onedir 专用 spec

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
            # 跳过 .pyd（由 binaries 处理）和 .so/.bin（非 Windows PE）
            if extension in ('.pyd', '.so', '.bin'):
                continue
            # TOC 格式: (dest_name, src_path, typecode)
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
    'app.modules',
    'app.plugins',
    # SQLAlchemy 异步方言（动态导入，PyInstaller 无法自动扫描）
    'aiosqlite',
    'sqlalchemy.dialects.sqlite',
    'sqlalchemy.dialects.sqlite.aiosqlite',
    'asyncpg',
    'sqlalchemy.dialects.postgresql',
    'sqlalchemy.dialects.postgresql.asyncpg',
] + collect_local_submodules('app.modules') + collect_local_submodules('app.plugins')

block_cipher = None

# 收集 app/helper/ 下的 .pyd 文件作为 binaries（格式: src, dest_dir）
helper_pyds = []
for pyd in _glob.glob('app/helper/*.pyd'):
    helper_pyds.append((pyd, 'app/helper'))

# .bin 文件作为 DATA，使用 TOC 格式: (dest_name, src_path, typecode)
helper_bin_toc = []
for bin_file in _glob.glob('app/helper/*.bin'):
    dest = str(_Path('app/helper') / _Path(bin_file).name)
    helper_bin_toc.append((dest, bin_file, 'DATA'))

# app.ico 以 TOC 格式加入
extra_datas = [('app.ico', 'app.ico', 'DATA')] + helper_bin_toc

a = Analysis(
    ['app/main.py'],
    pathex=[],
    binaries=helper_pyds,
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,   # onedir 模式
    name='MoviePilot',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,    # 调试模式：显示控制台窗口以便查看错误
    icon='app.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    collect_pkg_data('cf_clearance'),
    collect_pkg_data('zhconv'),
    collect_pkg_data('cn2an'),
    collect_pkg_data('Pinyin2Hanzi'),
    collect_pkg_data('database', include_py_files=True),
    collect_pkg_data('app.helper'),   # .pyd/.so/.bin 已排除，分别由 binaries/extra_datas 处理
    extra_datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='MoviePilot',
)
