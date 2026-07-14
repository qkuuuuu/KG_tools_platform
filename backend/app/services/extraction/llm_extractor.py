"""LLM Prompt 抽取器
基于大模型的 Schema 约束三元组抽取，支持分块上下文
参考: OpenSPG KAG Builder
"""
import json
import re
from typing import List, Dict, Optional
from app.config import settings


def _call_llm(cfg: Dict, system_prompt: str, user_prompt: str, temperature: float = 0.1) -> str:
    """统一 LLM 调用"""
    from openai import OpenAI
    import httpx

    base_url = cfg.get("base_url") or "https://api.openai.com/v1"
    client = OpenAI(api_key=cfg["api_key"], base_url=base_url, http_client=httpx.Client(timeout=120.0))

    provider = cfg.get("api_provider", "OPENAI")
    if provider == "ANTHROPIC":
        import anthropic
        ac = anthropic.Anthropic(api_key=cfg["api_key"])
        resp = ac.messages.create(
            model=cfg["model_name"], max_tokens=4096, temperature=temperature,
            system=system_prompt, messages=[{"role": "user", "content": user_prompt}],
        )
        return resp.content[0].text

    resp = client.chat.completions.create(
        model=cfg["model_name"], temperature=temperature,
        messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
    )
    return resp.choices[0].message.content


def _parse_triples_from_response(response: str) -> List[Dict]:
    """从 LLM 响应中解析 JSON 三元组数组"""
    resp = response.strip()
    resp = re.sub(r"```json\s*", "", resp)
    resp = re.sub(r"```\s*$", "", resp)
    start = resp.find("[")
    end = resp.rfind("]")
    if start >= 0 and end > start:
        try:
            return json.loads(resp[start:end + 1])
        except json.JSONDecodeError:
            pass
    return []


def extract_with_llm(
    md_content: str,
    schemas: List[Dict],
    cfg: Dict,
    chunk_size: int = 4000,
    max_schemas_in_prompt: int = 30,
    custom_prompt: str = None,
) -> List[Dict]:
    """LLM Prompt 抽取三元组

    参考 openSPG KAG 的做法：
    1. 将 Schema 作为约束注入 prompt
    2. 分块处理长文档
    3. 每块独立抽取后去重合并

    Args:
        md_content: Markdown 内容
        schemas: Schema 列表
        cfg: LLM 配置
        chunk_size: 分块大小
        max_schemas_in_prompt: prompt 中最大 schema 数量（避免 token 爆炸）
        custom_prompt: 用户自定义 Prompt（需求2）。若提供，则替换默认抽取指令，
                       但仍会自动追加 Schema 约束与输出格式要求，保证输出可解析。
    """
    if not md_content or not md_content.strip():
        return []

    from app.services.default_prompts import DEFAULT_EXTRACTION_PROMPT
    instruction = (custom_prompt.strip() if custom_prompt and custom_prompt.strip()
                   else DEFAULT_EXTRACTION_PROMPT)

    # 智能裁剪 schema（按相关性/频率选择 TOP N）
    schema_display = schemas[:max_schemas_in_prompt]
    if len(schemas) > max_schemas_in_prompt:
        schema_display_note = f"...（共 {len(schemas)} 条 Schema，仅展示前 {max_schemas_in_prompt} 条高频约束）"
    else:
        schema_display_note = ""

    schema_desc = "\n".join(
        f"- {s.get('subject_label') or s['subject_type']} --[{s.get('predicate_label') or s['predicate']}]--> {s.get('object_label') or s['object_type']}"
        for s in schema_display
    ) if schema_display else "（无 Schema 约束，自由抽取实体及关系）"

    system_prompt = f"""{instruction}

Schema 约束（只抽取符合以下模式的关系）：
{schema_desc}
{schema_display_note}

输出格式：严格 JSON 数组，每个元素：
{{"subject": "主语实体", "predicate": "关系谓语", "object": "宾语实体", "confidence": 0-100}}

规则：
1. 只输出 JSON 数组，禁止解释文字
2. confidence 为抽取可信度（0-100），对明显事实给高置信，模糊推断给低置信
3. 主语/宾语必须是文本中明确出现的具体实体名，不可用代词
4. 谓语必须与 Schema 定义一致
5. 无匹配时输出 []"""

    all_triples = []
    seen_keys = set()

    # 分块
    text = md_content
    chunks = []
    while text:
        if len(text) <= chunk_size:
            chunks.append(text)
            break
        # 优先在段落/句子边界切分
        cut = max(
            text[:chunk_size].rfind("\n\n"),
            text[:chunk_size].rfind("\n"),
            text[:chunk_size].rfind("。"),
            text[:chunk_size].rfind(". "),
            chunk_size,
        )
        chunks.append(text[:cut])
        text = text[cut:]

    for chunk_idx, chunk in enumerate(chunks):
        if not chunk.strip():
            continue
        try:
            user_prompt = f"""请从以下文本片段中抽取三元组（第 {chunk_idx + 1}/{len(chunks)} 块）：

{chunk[:3500]}"""

            response = _call_llm(cfg, system_prompt, user_prompt, temperature=0.05)
            triples = _parse_triples_from_response(response)

            for t in triples:
                # 事实核查：主语/宾语必须确定性出现在原文 chunk 中，
                # 否则视为幻觉三元组，丢弃（避免编造入库）。
                if settings.LLM_FACT_CHECK:
                    subj = (t.get("subject") or "").strip().strip('"').strip("'")
                    obj = (t.get("object") or "").strip().strip('"').strip("'")
                    if not subj or not obj:
                        continue
                    if subj not in chunk or obj not in chunk:
                        continue
                key = f"{t.get('subject','')}|{t.get('predicate','')}|{t.get('object','')}"
                if key not in seen_keys:
                    seen_keys.add(key)
                    t["source_chunk"] = chunk[:300]
                    all_triples.append(t)
        except Exception:
            continue

    return all_triples
