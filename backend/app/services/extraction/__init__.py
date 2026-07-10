"""多方法知识抽取引擎池 (Multi-Method Extraction Pool)
参考: OpenSPG / QKnow 架构设计
引擎类型:
  - LLM_PROMPT: 大模型 Prompt 抽取（冷启动/无训练场景）
  - CUSTOM_SCRIPT: 用户上传 Python 脚本自定义抽取
  - GLINER: 轻量级零样本 NER（GLiNER 多语言模型）
  - UIE: 百度统一信息抽取框架（少样本）
  - DEEPKE: ModelScope RaNER 中文通用 NER + 关系配对
"""
import traceback
from typing import List, Dict, Optional


# 引擎注册表
EXTRACTION_ENGINES = {
    "LLM_PROMPT": "LLM Prompt 抽取（大模型）",
    "CUSTOM_SCRIPT": "自定义 Python 脚本",
    "GLINER": "零样本 NER (GLiNER 多语言)",
    "UIE": "统一信息抽取 (百度 UIE)",
    "DEEPKE": "ModelScope RaNER 中文通用 NER + 关系配对",
}


def _check_engine_import(module_name: str, func_name: str) -> bool:
    """检查引擎函数是否可导入"""
    try:
        mod = __import__(f"app.services.extraction.{module_name}", fromlist=[func_name])
        return hasattr(mod, func_name)
    except Exception as e:
        return False


def get_available_engines() -> List[Dict]:
    """返回已安装可用的引擎列表"""
    available = []
    
    # LLM 总是可用
    available.append({
        "key": "LLM_PROMPT", "name": "LLM Prompt 抽取",
        "status": "ready", "description": "基于大模型按 Schema 抽取三元组，适合冷启动"
    })
    
    # 自定义脚本引擎总是可用
    available.append({
        "key": "CUSTOM_SCRIPT", "name": "自定义 Python 脚本",
        "status": "ready", "description": "上传 Python 脚本自定义抽取逻辑，灵活适配任意场景"
    })
    
    # GLiNER
    if _check_engine_import("gliner_extractor", "extract_with_gliner"):
        available.append({
            "key": "GLINER", "name": "GLiNER 零样本 NER (多语言)",
            "status": "ready", "description": "多语言零样本实体识别，支持中文原生标签"
        })
    else:
        available.append({
            "key": "GLINER", "name": "GLiNER 零样本 NER (多语言)",
            "status": "unavailable",
            "description": "需要安装: pip install gliner spacy && python -m spacy download en_core_web_sm"
        })

    # UIE
    if _check_engine_import("uie_extractor", "extract_with_uie"):
        available.append({
            "key": "UIE", "name": "百度 UIE 统一信息抽取",
            "status": "ready", "description": "少样本情境学习，支持 Schema 约束"
        })
    else:
        available.append({
            "key": "UIE", "name": "百度 UIE 统一信息抽取",
            "status": "unavailable",
            "description": "需要安装: pip install paddlenlp"
        })

    # CasRel 引擎已移除（降级方案质量不足，直接删除）

    # DeepKE (ModelScope)
    if _check_engine_import("deepke_extractor", "extract_with_deepke"):
        available.append({
            "key": "DEEPKE", "name": "ModelScope RaNER 中文通用 NER",
            "status": "ready", "description": "基于 ModelScope RaNER 中文通用 NER 模型的实体识别+关系配对"
        })
    else:
        available.append({
            "key": "DEEPKE", "name": "ModelScope RaNER 中文通用 NER",
            "status": "unavailable",
            "description": "需要安装: pip install modelscope"
        })

    return available


def extract_triples(
    method: str,
    md_content: str,
    schemas: List[Dict],
    cfg: Optional[Dict] = None,
    device_config: Optional[Dict] = None,
    **kwargs,
) -> List[Dict]:
    """统一抽取入口
    
    Args:
        method: 抽取方法 (LLM_PROMPT / CUSTOM_SCRIPT / GLINER / UIE / DEEPKE)
        md_content: 文档 Markdown 内容
        schemas: Schema 约束列表
        cfg: LLM 配置（仅 LLM_PROMPT 需要）
        device_config: 设备配置 {"UIE": {"device": "CPU"/"GPU", "gpu_id": 0}, ...}
        **kwargs: 传给具体引擎的额外参数 (如 script_id)
    
    Returns:
        [{"subject":..., "predicate":..., "object":..., "confidence": float, "chunk":...}]
    """
    # 提取当前方法的设备配置
    dev_cfg = (device_config or {}).get(method, {})
    use_gpu = dev_cfg.get("device", "CPU").upper() == "GPU"
    gpu_id = dev_cfg.get("gpu_id", 0)

    if method == "LLM_PROMPT":
        from .llm_extractor import extract_with_llm
        return extract_with_llm(md_content, schemas, cfg, **kwargs)
    
    elif method == "CUSTOM_SCRIPT":
        from .custom_script_extractor import extract_with_custom_script
        return extract_with_custom_script(md_content, schemas, **kwargs)
    
    elif method == "GLINER":
        from .gliner_extractor import extract_with_gliner
        return extract_with_gliner(md_content, schemas, use_gpu=use_gpu, gpu_id=gpu_id, **kwargs)
    
    elif method == "UIE":
        from .uie_extractor import extract_with_uie
        return extract_with_uie(md_content, schemas, use_gpu=use_gpu, gpu_id=gpu_id, **kwargs)
    
    elif method == "DEEPKE":
        from .deepke_extractor import extract_with_deepke
        return extract_with_deepke(md_content, schemas, use_gpu=use_gpu, gpu_id=gpu_id, **kwargs)
    
    else:
        raise ValueError(f"未知抽取方法: {method}，可用: {list(EXTRACTION_ENGINES.keys())}")
