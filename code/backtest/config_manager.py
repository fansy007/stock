"""
配置组合管理器

目录结构：
    config_sets/
    ├── default/          # 系统模板（只读）
    │   └── 组合名/
    │       ├── backtest.json
    │       ├── buy.json
    │       └── sell.json
    └── custom/           # 用户自定义
        └── 组合名/
            ├── backtest.json
            ├── buy.json
            └── sell.json

组合 = 三个配置文件的集合，命名就是目录名。
"""

import os
import json
import shutil

BASE = os.path.join(os.path.dirname(__file__), 'config_sets')


def list_sets() -> list:
    """列出所有配置组合，返回 [(名称, 类型), ...] 按名称排序"""
    result = []
    for kind in ('default', 'custom'):
        root = os.path.join(BASE, kind)
        if not os.path.isdir(root):
            continue
        for name in sorted(os.listdir(root)):
            d = os.path.join(root, name)
            if os.path.isdir(d):
                result.append((name, kind))
    return result


def get_path(name: str, kind: str) -> str:
    """获取组合目录路径"""
    return os.path.join(BASE, kind, name)


def load_set(name: str, kind: str) -> dict:
    """加载一个配置组合，返回 {backtest: dict, buy: dict, sell: dict}"""
    d = get_path(name, kind)
    result = {}
    for key, fn in [('backtest', 'backtest.json'), ('buy', 'buy.json'), ('sell', 'sell.json')]:
        fp = os.path.join(d, fn)
        if os.path.exists(fp):
            with open(fp, 'r', encoding='utf-8') as f:
                result[key] = json.load(f)
        else:
            result[key] = {}
    return result


def save_set(name: str, configs: dict):
    """保存/覆盖一个自定义组合。configs = {backtest: dict, buy: dict, sell: dict}"""
    d = get_path(name, 'custom')
    os.makedirs(d, exist_ok=True)
    for key, fn in [('backtest', 'backtest.json'), ('buy', 'buy.json'), ('sell', 'sell.json')]:
        fp = os.path.join(d, fn)
        with open(fp, 'w', encoding='utf-8') as f:
            json.dump(configs.get(key, {}), f, ensure_ascii=False, indent=2)


def delete_set(name: str):
    """删除自定义组合"""
    d = get_path(name, 'custom')
    if os.path.isdir(d):
        shutil.rmtree(d)


def create_from_template(name: str, template_name: str):
    """从模板创建新组合"""
    src = get_path(template_name, 'default')
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
