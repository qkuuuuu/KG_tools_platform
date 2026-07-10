"""自定义脚本抽取器 (Custom Script Extractor)
用户上传 Python 脚本，动态加载并调用 extract(md_content, schemas) → triples
约定接口: def extract(md_content: str, schemas: list) -> list
"""
import os
import sys
import uuid
import time
import importlib.util
import traceback
from typing import List, Dict, Optional

# 脚本存储目录
SCRIPTS_DIR = os.path.join(os.getcwd(), "uploads", "scripts")
os.makedirs(SCRIPTS_DIR, exist_ok=True)

# 已加载模块缓存: {script_id: module}
_MODULE_CACHE = {}

# 脚本元数据: {script_id: {"filename": ..., "path": ..., "description": ..., "uploaded_at": ...}}
_SCRIPT_META = {}


def _scan_scripts():
    """扫描脚本目录，加载元数据"""
    if not os.path.isdir(SCRIPTS_DIR):
        return
    for fname in os.listdir(SCRIPTS_DIR):
        if not fname.endswith(".py"):
            continue
        filepath = os.path.join(SCRIPTS_DIR, fname)
        stat = os.stat(filepath)
        script_id = fname[:-3]  # 去掉 .py
        _SCRIPT_META[script_id] = {
            "script_id": script_id,
            "filename": fname,
            "path": filepath,
            "description": "",
            "uploaded_at": stat.st_mtime,
            "size": stat.st_size,
        }


# 启动时扫描一次
_scan_scripts()


def save_uploaded_script(filename: str, content: bytes, description: str = "") -> Dict:
    """保存上传的脚本文件
    
    Args:
        filename: 原始文件名
        content: 文件内容字节
        description: 脚本说明
    
    Returns:
        {"script_id": ..., "filename": ..., "description": ..., "size": ...}
    """
    # 限制文件大小 1MB
    if len(content) > 1 * 1024 * 1024:
        raise ValueError("脚本文件超过 1MB 限制")

    # 安全文件名: 只保留字母数字下划线连字符
    safe_name = "".join(c for c in filename if c.isalnum() or c in "_-")
    if not safe_name:
        safe_name = "custom_script"
    if not safe_name.endswith(".py"):
        safe_name += ".py"

    # 生成唯一 script_id
    script_id = f"{safe_name[:-3]}_{uuid.uuid4().hex[:8]}"
    dest_filename = f"{script_id}.py"
    dest_path = os.path.join(SCRIPTS_DIR, dest_filename)

    with open(dest_path, "wb") as f:
        f.write(content)

    _SCRIPT_META[script_id] = {
        "script_id": script_id,
        "filename": filename,
        "path": dest_path,
        "description": description,
        "uploaded_at": time.time(),
        "size": len(content),
    }

    return _SCRIPT_META[script_id]


def list_scripts() -> List[Dict]:
    """列出所有已上传脚本"""
    _scan_scripts()
    result = []
    for sid, meta in _SCRIPT_META.items():
        result.append({
            "script_id": sid,
            "filename": meta["filename"],
            "description": meta.get("description", ""),
            "size": meta.get("size", 0),
        })
    return result


def delete_script(script_id: str) -> bool:
    """删除脚本"""
    meta = _SCRIPT_META.pop(script_id, None)
    if meta is None:
        # 尝试扫描
        _scan_scripts()
        meta = _SCRIPT_META.pop(script_id, None)
    if meta is None:
        return False

    filepath = meta.get("path", "")
    if filepath and os.path.exists(filepath):
        os.remove(filepath)

    # 清除模块缓存
    if script_id in _MODULE_CACHE:
        del _MODULE_CACHE[script_id]

    return True


def _load_script_module(script_id: str):
    """动态加载 Python 脚本模块"""
    if script_id in _MODULE_CACHE:
        return _MODULE_CACHE[script_id]

    _scan_scripts()
    meta = _SCRIPT_META.get(script_id)
    if meta is None:
        raise ValueError(f"脚本不存在: {script_id}")

    filepath = meta["path"]
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"脚本文件不存在: {filepath}")

    module_name = f"custom_script_{script_id}"
    spec = importlib.util.spec_from_file_location(module_name, filepath)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载脚本模块: {script_id}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    # 验证接口
    if not hasattr(module, "extract") or not callable(module.extract):
        raise AttributeError(f"脚本 {script_id} 缺少 extract(md_content: str, schemas: list) -> list 函数")

    _MODULE_CACHE[script_id] = module
    return module


def extract_with_custom_script(
    md_content: str,
    schemas: List[Dict],
    script_id: str = "",
    **kwargs,
) -> List[Dict]:
    """使用自定义脚本抽取三元组
    
    Args:
        md_content: Markdown 文本
        schemas: Schema 约束列表
        script_id: 脚本 ID
    
    Returns:
        三元组列表
    """
    if not md_content or not md_content.strip():
        return []

    if not script_id:
        raise ValueError("自定义脚本抽取需要指定 script_id")

    module = _load_script_module(script_id)

    # 执行超时 60 秒 (使用 threading，兼容 Windows)
    import threading

    result_holder = {"result": None, "error": None}

    def _run():
        try:
            raw_result = module.extract(md_content, schemas)
            result_holder["result"] = raw_result
        except Exception as e:
            result_holder["error"] = e

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout=60)

    if thread.is_alive():
        # 线程仍在运行，超时
        raise TimeoutError("脚本执行超时 (60s)")

    if result_holder["error"]:
        raise result_holder["error"]

    raw = result_holder["result"]
    if not raw or not isinstance(raw, list):
        return []

    # 标准化输出格式
    triples = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        triples.append({
            "subject": str(item.get("subject", "")),
            "predicate": str(item.get("predicate", "")),
            "object": str(item.get("object", "")),
            "confidence": None,
            "extraction_method": "CUSTOM_SCRIPT",
            "chunk": str(item.get("chunk", ""))[:500],
        })

    return triples
