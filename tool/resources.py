"""读取 resource/ 下的可复用映射表（JSON）。

表清单与各自的使用者见 resource/ 下各文件的 _comment 字段。脚本不再各自硬编码
这些映射，统一从这里取，避免多份数据漂移。
"""
import json
from pathlib import Path

RESOURCE_DIR = Path(__file__).resolve().parent.parent / 'resource'


def load(name):
    """读取 resource/<name>，返回解析后的 JSON。"""
    with open(RESOURCE_DIR / name, encoding='utf-8') as fh:
        return json.load(fh)
