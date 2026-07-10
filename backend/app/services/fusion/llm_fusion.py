"""LLM 辅助实体消歧 (LLM-Assisted Entity Disambiguation)
参考 QKnow: AI初筛 + 人工复核 协同模式
用于处理编辑距离难以消歧的歧义实体
"""
import json
import re
import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


def _call_llm_for_fusion(cfg: Dict, system_prompt: str, user_prompt: str) -> str:
    """LLM 消歧调用"""
    from openai import OpenAI
    import httpx

    base_url = cfg.get("base_url") or "https://api.openai.com/v1"
    client = OpenAI(api_key=cfg["api_key"], base_url=base_url, http_client=httpx.Client(timeout=60.0))

    provider = cfg.get("api_provider", "OPENAI")
    if provider == "ANTHROPIC":
        import anthropic
        ac = anthropic.Anthropic(api_key=cfg["api_key"])
        resp = ac.messages.create(
            model=cfg["model_name"], max_tokens=2048, temperature=0.0,
            system=system_prompt, messages=[{"role": "user", "content": user_prompt}],
        )
        return resp.content[0].text

    resp = client.chat.completions.create(
        model=cfg["model_name"], temperature=0.0,
        messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
    )
    return resp.choices[0].message.content


def llm_assisted_fusion(
    entity_pairs: List[Dict],
    context_text: str,
    cfg: Dict,
    batch_size: int = 15,
) -> List[Dict]:
    """用 LLM 辅助判断歧义实体对是否为同一实体
    
    参考 QKnow 设计: AI 初筛 + 给出融合/不融合建议 + 人工最终确认
    
    Args:
        entity_pairs: [{"entity_1":..., "entity_2":..., "similarity":...}]
        context_text: 包含这些实体的上下文文本（用于消歧判断）
        cfg: LLM 配置（建议用 VERIFICATION 阶段的反思模型）
        batch_size: 每批处理的实体对数
    
    Returns:
        更新后的 entity_pairs，每项增加 suggestion 和 reason
    """
    if not entity_pairs:
        return []

    system_prompt = """你是知识图谱实体融合专家。
参考 QKnow 的知识融合设计理念，判断两个实体名是否指向同一实体。

输出格式: 严格 JSON 数组:
[{"index": 0, "decision": "MERGE/DISTINCT/UNCERTAIN", "reason": "简短原因"}]

判断规则:
- MERGE: 明显同一实体（缩写/别名/大小写/中英文名对应）
  例: "华为"→"华为技术有限公司" MERGE; "Apple Inc."→"苹果公司" MERGE
- DISTINCT: 明显不同实体
  例: "华为"→"华为手机" 如果上下文表明一个是公司一个是产品，DISTINCT
- UNCERTAIN: 无法确定，需要人工判断"""

    results = list(entity_pairs)

    for batch_start in range(0, len(results), batch_size):
        batch = results[batch_start:batch_start + batch_size]

        pairs_text = "\n".join(
            f"{i}. [{pair['entity_1']}] vs [{pair['entity_2']}] (算法相似度: {pair.get('similarity', 'N/A')}%)"
            for i, pair in enumerate(batch)
        )

        user_prompt = f"""上下文文本（用于消歧参考）:
{context_text[:2500]}

待判断的实体对:
{pairs_text}

请对以上每种实体对进行融合判断。"""

        try:
            response = _call_llm_for_fusion(cfg, system_prompt, user_prompt)
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
                    actual_idx = batch_start + idx
                    if actual_idx >= 0 and actual_idx < len(results):
                        results[actual_idx]["llm_decision"] = d.get("decision", "UNCERTAIN")
                        results[actual_idx]["llm_reason"] = d.get("reason", "")
                        # 转换决策
                        decision = d.get("decision", "UNCERTAIN")
                        if decision == "MERGE":
                            results[actual_idx]["suggestion"] = "LLM_SUGGEST_MERGE"
                        elif decision == "DISTINCT":
                            results[actual_idx]["suggestion"] = "LLM_SUGGEST_KEEP_SEPARATE"
                        else:
                            results[actual_idx]["suggestion"] = "MANUAL_CONFIRM"
        except Exception as e:
            logger.warning(f"LLM 消歧批次失败: {e}")
            continue

    return results
