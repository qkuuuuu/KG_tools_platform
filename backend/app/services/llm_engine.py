"""LLM 抽取引擎 - 调用 OpenAI/Anthropic/DeepSeek/Qwen API
支持:
  - LLM_PROMPT: 按 Schema 生成三元组
  - LLM 质检: 反思打分
"""
import json
import re
from typing import List, Dict, Optional
from openai import OpenAI
import httpx


def _get_llm_config(db, project_id: str, stage: str):
    """从数据库获取某阶段的 LLM 配置"""
    from app.models import LLMConfig
    from app.config import decrypt_value
    
    cfg = db.query(LLMConfig).filter(
        LLMConfig.project_id == project_id,
        LLMConfig.pipeline_stage == stage,
    ).first()
    
    if not cfg:
        return None
    
    return {
        "api_provider": cfg.api_provider,
        "base_url": cfg.base_url,
        "api_key": decrypt_value(cfg.api_key_encrypted),
        "model_name": cfg.model_name,
        "prompt": cfg.prompt or "",  # 自定义 Prompt（需求1/2），前端可编辑
        "enabled": bool(getattr(cfg, "enabled", True)),  # 向量模型开关（需求4）：默认开启
    }


def _make_client(cfg: Dict):
    """创建 OpenAI 兼容客户端（DeepSeek/Qwen 也兼容 OpenAI 格式）"""
    base_url = cfg.get("base_url") or "https://api.openai.com/v1"
    return OpenAI(
        api_key=cfg["api_key"],
        base_url=base_url,
        http_client=httpx.Client(timeout=120.0),
    )


def _call_llm(cfg: Dict, system_prompt: str, user_prompt: str, temperature: float = 0.1) -> str:
    """统一调用 LLM，返回文本响应"""
    client = _make_client(cfg)
    
    provider = cfg.get("api_provider", "OPENAI")
    
    if provider == "ANTHROPIC":
        # Anthropic 用单独的 SDK
        import anthropic
        ac = anthropic.Anthropic(api_key=cfg["api_key"])
        if cfg.get("base_url"):
            ac = anthropic.Anthropic(api_key=cfg["api_key"], base_url=cfg["base_url"])
        resp = ac.messages.create(
            model=cfg["model_name"],
            max_tokens=4096,
            temperature=temperature,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return resp.content[0].text
    
    # OpenAI / DeepSeek / Qwen 都走 OpenAI 格式
    resp = client.chat.completions.create(
        model=cfg["model_name"],
        temperature=temperature,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    return resp.choices[0].message.content


def extract_triples_with_llm(
    md_content: str,
    schemas: List[Dict],
    cfg: Dict,
    chunk_size: int = 3000,
    custom_prompt: str = None,
) -> List[Dict]:
    """用 LLM 按 Schema 从 Markdown 中抽取三元组
    
    Args:
        md_content: 文档 Markdown 内容
        schemas: Schema 约束列表 [{"subject_type":..., "predicate":..., "object_type":...}]
        cfg: LLM 配置
        chunk_size: 分块大小（字符数）
    
    Returns:
        [{"subject":..., "predicate":..., "object":..., "confidence": float, "chunk":...}]
    """
    if not md_content or not md_content.strip():
        return []
    
    # 构建 Schema 描述
    schema_desc = "\n".join(
        f"- {s['subject_type']} --[{s['predicate']}]--> {s['object_type']}"
        for s in schemas
    ) if schemas else "（无约束，自由抽取实体关系）"
    
    system_prompt = f"""你是知识图谱三元组抽取专家。
从给定文本中抽取 (主语, 谓语, 宾语) 三元组。

Schema 约束（只抽取符合这些模式的关系）:
{schema_desc}

输出格式: 严格 JSON 数组，每个元素:
{{"subject": "主语", "predicate": "谓语", "object": "宾语", "confidence": 0.0-100.0}}

要求:
1. 只输出 JSON 数组，不要任何解释文字
2. confidence 是你对该三元组正确性的自信度 (0-100)
3. 主语/宾语必须是具体实体，不能是代词
4. 谓语必须与 Schema 中的 predicate 一致
5. 如果文本中没有符合的三元组，输出 []"""

    all_triples = []
    
    # 分块处理
    text = md_content
    chunks = []
    while text:
        if len(text) <= chunk_size:
            chunks.append(text)
            break
        # 在句号/换行处切分
        cut = text[:chunk_size].rfind("\n")
        if cut < chunk_size // 2:
            cut = text[:chunk_size].rfind("。")
        if cut < chunk_size // 2:
            cut = chunk_size
        chunks.append(text[:cut])
        text = text[cut:]
    
    for chunk in chunks:
        if not chunk.strip():
            continue
        try:
            user_prompt = f"请从以下文本中抽取三元组:\n\n{chunk}"
            response = _call_llm(cfg, system_prompt, user_prompt)
            
            # 解析 JSON
            # 去除可能的 markdown 代码块
            response = re.sub(r"```json\s*", "", response)
            response = re.sub(r"```\s*", "", response)
            response = response.strip()
            
            # 找到第一个 [ 和最后一个 ]
            start = response.find("[")
            end = response.rfind("]")
            if start >= 0 and end > start:
                json_str = response[start:end+1]
                triples = json.loads(json_str)
                for t in triples:
                    t["chunk"] = chunk[:500]  # 保留来源片段
                    all_triples.append(t)
        except Exception as e:
            # 单块失败不影响其他块
            continue
    
    return all_triples


def quality_check_with_llm(
    triples: List[Dict],
    md_content: str,
    cfg: Dict,
) -> List[Dict]:
    """用 LLM 对三元组进行反思质检，返回更新后的三元组（带新 confidence）
    
    Args:
        triples: 待质检的三元组列表
        md_content: 原始文档内容
        cfg: LLM 配置
    
    Returns:
        更新后的三元组列表，每个元素新增 "quality_score" 字段
    """
    if not triples:
        return []
    
    system_prompt = """你是知识图谱质量审核专家。
给定一批三元组和原始文本，请对每条三元组进行验证:
1. 主语/宾语是否在原文中明确出现
2. 谓语关系是否正确
3. 是否存在幻觉（LLM 编造的内容）

输出格式: 严格 JSON 数组，每个元素:
{"index": 0, "quality_score": 0-100, "reason": "简短原因"}

只输出 JSON，不要解释。"""

    # 批量处理（每批最多 20 条）
    results = []
    for batch_start in range(0, len(triples), 20):
        batch = triples[batch_start:batch_start + 20]
        batch_text = "\n".join(
            f"{i}. ({t['subject']}, {t['predicate']}, {t['object']})"
            for i, t in enumerate(batch)
        )
        user_prompt = f"""原始文本片段:
{md_content[:2000]}

待审核三元组:
{batch_text}

请审核以上三元组。"""
        
        try:
            response = _call_llm(cfg, system_prompt, user_prompt)
            response = re.sub(r"```json\s*", "", response)
            response = re.sub(r"```\s*", "", response)
            start = response.find("[")
            end = response.rfind("]")
            if start >= 0 and end > start:
                scores = json.loads(response[start:end+1])
                for s in scores:
                    idx = s.get("index", 0)
                    if 0 <= idx < len(batch):
                        batch[idx]["quality_score"] = float(s.get("quality_score", 50))
                        batch[idx]["quality_reason"] = s.get("reason", "")
                        results.append(batch[idx])
        except Exception:
            # 失败时保留原 confidence
            for t in batch:
                t["quality_score"] = t.get("confidence", 50.0)
                results.append(t)
    
    return results


def get_llm_config_for_project(db, project_id: str, stage: str = "EXTRACTION"):
    """外部调用入口: 获取项目的 LLM 配置"""
    return _get_llm_config(db, project_id, stage)


def get_embeddings(texts, cfg: Dict) -> List[List[float]]:
    """调用 OpenAI 兼容的向量(Embedding)模型，返回每条文本的向量

    用于「三元组入库前消歧」的向量语义相似度（需求4）。cfg 为 EMBEDDING
    阶段的 LLM 配置（base_url / api_key / model_name）。

    Args:
        texts: 单个字符串或字符串列表
        cfg: EMBEDDING 阶段配置
    Returns:
        与输入顺序一致的向量列表
    """
    if isinstance(texts, str):
        texts = [texts]
    # 过滤空文本，用占位空格代替，保证与输入等长对齐
    clean = [(t if (t and t.strip()) else " ") for t in texts]
    if not clean:
        return []

    client = _make_client(cfg)
    resp = client.embeddings.create(model=cfg["model_name"], input=clean)
    data = resp.data
    # 兼容两种返回格式：
    # 1) OpenAI 官方返回带 index 字段，且 index 按顺序 → 按 index 还原输入顺序（最稳妥）。
    # 2) 部分 OpenAI 兼容服务不返回 index，或无序返回 → 若 index 不可靠，则信任服务
    #    按输入顺序返回（绝大多数实现如此），直接按返回顺序映射即可（Python 切片保序）。
    indices = [getattr(d, "index", None) for d in data]
    if (
        len(indices) == len(clean)
        and all(isinstance(i, int) and 0 <= i < len(clean) for i in indices)
        and len(set(indices)) == len(indices)
    ):
        ordered = [None] * len(clean)
        for d, i in zip(data, indices):
            ordered[i] = list(d.embedding)
        return ordered
    return [list(d.embedding) for d in data]


def disambiguate_triples_with_llm(
    candidates: List[Dict],
    similar_map: Dict,
    cfg: Dict,
    custom_prompt: str = None,
) -> List[Dict]:
    """对一批待消歧三元组调用 LLM 进行消歧（需求5）

    Args:
        candidates: [{"id", "subject", "predicate", "object", "confidence"}]
        similar_map: { triple_id: [语义相似的已有三元组...] }
        cfg: LLM 配置（DISAMBIGUATION 阶段；回退 VERIFICATION）
        custom_prompt: 用户自定义消歧 Prompt（可选）
    Returns:
        解析后的候选三元组（可能被 LLM 归一为规范表述），附带
        disambiguation_decision / disambiguation_reason
    """
    if not candidates:
        return []

    from app.services.default_prompts import DEFAULT_DISAMBIGUATION_PROMPT
    instruction = (custom_prompt.strip() if custom_prompt and custom_prompt.strip()
                   else DEFAULT_DISAMBIGUATION_PROMPT)

    results = list(candidates)
    for batch_start in range(0, len(results), 10):
        batch = results[batch_start:batch_start + 10]

        cand_text = "\n".join(
            f"{i}. 待消歧: ({c.get('subject')}, {c.get('predicate')}, {c.get('object')}) [confidence={c.get('confidence')}]"
            for i, c in enumerate(batch)
        )
        sim_text = ""
        for i, c in enumerate(batch):
            sims = similar_map.get(str(c.get("id", "")), [])[:5]
            if sims:
                sim_text += f"\n[{i}] 语义相似的已有三元组:\n"
                for s in sims:
                    sim_text += f"   - ({s.get('subject')}, {s.get('predicate')}, {s.get('object')}) 相似度={s.get('similarity')}\n"

        user_prompt = f"""待消歧三元组：
{cand_text}
{sim_text}
请逐条判断并输出消歧结果。"""

        try:
            response = _call_llm(cfg, instruction, user_prompt, temperature=0.0)
            response = re.sub(r"```json\s*", "", response)
            response = re.sub(r"```\s*", "", response)
            start = response.find("[")
            end = response.rfind("]")
            if start >= 0 and end > start:
                decisions = json.loads(response[start:end + 1])
                for d in decisions:
                    idx = d.get("index", 0)
                    if not isinstance(idx, int):
                        continue
                    actual = batch_start + idx
                    if 0 <= actual < len(results):
                        decision = d.get("decision", "KEEP")
                        if decision == "MERGE":
                            results[actual]["subject"] = d.get("subject", results[actual]["subject"])
                            results[actual]["predicate"] = d.get("predicate", results[actual]["predicate"])
                            results[actual]["object"] = d.get("object", results[actual]["object"])
                        results[actual]["disambiguation_decision"] = decision
                        results[actual]["disambiguation_reason"] = d.get("reason", "")
        except Exception:
            continue

    return results



def call_llm_api(cfg: Dict, system_prompt: str, user_prompt: str, temperature: float = 0.1) -> str:
    """外部调用入口: 调用 LLM API，返回文本响应"""
    return _call_llm(cfg, system_prompt, user_prompt, temperature)
