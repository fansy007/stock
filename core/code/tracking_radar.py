"""
跟踪雷达 — 配置组合管理器

目录结构：
    core/code/tracking_radar/config_sets/
    ├── default/          # 系统模板（只读）
    │   └── 模板名/
    │       └── tracking.json
    └── custom/           # 用户自定义
        └── 组合名/
            └── tracking.json

tracking.json = [{ name, search?, check_points[] }]
"""
import os
import json
import shutil

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config_sets')


def list_sets() -> list:
    """列出所有配置组合，返回 [(名称, 类型=default|custom), ...]"""
    result = []
    for kind in ('default', 'custom'):
        root = os.path.join(BASE, kind)
        if not os.path.isdir(root):
            continue
        for name in sorted(os.listdir(root)):
            if os.path.isdir(os.path.join(root, name)):
                result.append((name, kind))
    return result


def get_path(name: str, kind: str) -> str:
    """获取组合目录路径"""
    return os.path.join(BASE, kind, name)


def load_set(name: str, kind: str) -> list:
    """加载一个配置组合，返回 topic 列表"""
    fp = os.path.join(get_path(name, kind), 'tracking.json')
    if os.path.exists(fp):
        with open(fp, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
    return []


def save_set(name: str, topics: list):
    """保存/覆盖一个自定义组合的 topic 列表"""
    d = get_path(name, 'custom')
    os.makedirs(d, exist_ok=True)
    fp = os.path.join(d, 'tracking.json')
    with open(fp, 'w', encoding='utf-8') as f:
        json.dump(topics, f, ensure_ascii=False, indent=2)


def delete_set(name: str):
    """删除自定义组合"""
    d = get_path(name, 'custom')
    if os.path.isdir(d):
        shutil.rmtree(d)


def copy_set(name: str, source_name: str, source_kind: str):
    """从任意 source（default 或 custom）复制为新组合"""
    src = get_path(source_name, source_kind)
    dst = get_path(name, 'custom')
    if os.path.isdir(dst):
        raise FileExistsError(f"组合 '{name}' 已存在")
    shutil.copytree(src, dst)


def rename_set(old_name: str, new_name: str):
    """重命名自定义组合"""
    src = get_path(old_name, 'custom')
    dst = get_path(new_name, 'custom')
    if not os.path.isdir(src):
        raise FileNotFoundError(f"组合 '{old_name}' 不存在")
    if os.path.isdir(dst):
        raise FileExistsError(f"组合 '{new_name}' 已存在")
    os.rename(src, dst)

