import json
from pathlib import Path
from typing import Optional, Tuple

def load_key_from_jsons(usm_stem: str, base_path: Path, increment_path: Optional[Path] = None) -> Optional[int]:
    """
    尝试从 base/increment json 查找 key，优先增量，后基础。
    :param usm_stem: usm 文件名（不含扩展名）
    :param base_path: base json 路径
    :param increment_path: increment json 路径（可选）
    :return: key int 或 None
    """
    key_hex = None
    # 先查增量
    if increment_path and increment_path.exists():
        try:
            with increment_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            key_hex = data.get(usm_stem)
        except Exception:
            pass
    # 再查基础
    if key_hex is None and base_path.exists():
        try:
            with base_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            key_hex = data.get(usm_stem)
        except Exception:
            pass
    if key_hex:
        try:
            return int(key_hex, 16)
        except Exception:
            return None
    return None
