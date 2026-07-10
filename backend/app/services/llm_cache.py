"""LLM 抽取结果缓存
避免同一文档+Schema+模型的重复 LLM 调用
"""
import hashlib
import json
import os
import time
from typing import List, Dict, Optional, Tuple

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", ".cache", "llm_extract")
CACHE_TTL_SECONDS = 24 * 3600  # 24 小时


def _cache_key(doc_id: str, model_name: str, schema_hash: str, method: str) -> str:
    raw = f"{doc_id}|{model_name}|{schema_hash}|{method}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _schema_hash(schemas: List[Dict]) -> str:
    schema_str = json.dumps(schemas, sort_keys=True, ensure_ascii=False)
    return hashlib.md5(schema_str.encode()).hexdigest()[:16]


def get_cached_result(
    doc_id: str, model_name: str, schemas: List[Dict], method: str,
) -> Optional[List[Dict]]:
    """获取缓存的抽取结果"""
    key = _cache_key(doc_id, model_name, _schema_hash(schemas), method)
    path = os.path.join(CACHE_DIR, f"{key}.json")
    if not os.path.exists(path):
        return None
    mtime = os.path.getmtime(path)
    if time.time() - mtime > CACHE_TTL_SECONDS:
        os.remove(path)
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def set_cached_result(
    doc_id: str, model_name: str, schemas: List[Dict], method: str,
    result: List[Dict],
):
    """写入缓存"""
    os.makedirs(CACHE_DIR, exist_ok=True)
    key = _cache_key(doc_id, model_name, _schema_hash(schemas), method)
    path = os.path.join(CACHE_DIR, f"{key}.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False)
    except Exception:
        pass
