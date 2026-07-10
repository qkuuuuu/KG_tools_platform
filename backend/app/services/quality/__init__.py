"""质检服务 (Quality Check)
LLM 反思评分 + 规则校验
参考: QKnow 置信度审批层
"""
import json
import re
from typing import List, Dict, Optional


def _call_llm_for_quality(cfg: Dict, system_prompt: str, user_prompt: str) -> str:
    from openai import OpenAI
    import httpx
    base_url = cfg.get("base_url") or "https://api.openai.com/v1"
    client = OpenAI(api_key=cfg["api_key"], base_url=base_url, http_client=httpx.Client(timeout=60.0))
    resp = client.chat.completions.create(
        model=cfg["model_name"], temperature=0.0,
        messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
    )
    return resp.choices[0].message.content


def llm_quality_review(
    triples: List[Dict],
    md_content: str,
    cfg: Dict,
    threshold: float = 90.0,
    batch_size: int = 15,
    benchmark_content: str = "",
) -> List[Dict]:
    """LLM 对三元组进行反思评分，返回带新置信度的三元组
    
    流程:
      1. 逐条对照原文验证
      2. 检测幻觉（编造的内容）
      3. 给出质量评分
      4. 标记通过/拦截
    
    Args:
        triples: 待质检三元组
        md_content: 原始文档
        cfg: LLM 配置 (VERIFICATION 阶段)
        threshold: 通过阈值
        batch_size: 每批数量
        benchmark_content: 质检基准文件内容（约束文档/规范），由用户上传，可选
    
    Returns:
        更新后的三元组（新增 quality_score, verdict, reason）
    """
    if not triples:
        return []

    system_prompt = """你是知识图谱质量审核员。
对每条三元组进行严格审核：
1. 主语/宾语是否在原文中明确出现
2. 谓语关系是否正确反映原文语义
3. 是否存在幻觉（LLM 编造不存在的事实）
4. 实体边界是否完整（如：公司名是否包含"有限公司"后缀）

输出格式: JSON 数组:
[{"index": 0, "quality_score": 0-100, "verdict": "PASS/REJECT/UNCERTAIN", "reason": "简短原因"}]

评分标准:
90-100: 完全正确，主语宾语均在原文，关系准确
70-89: 基本正确，但实体边界或关系表述略有问题
40-69: 存在怀疑点，可能部分错误
0-39: 明显错误或幻觉

只输出 JSON，无需解释。"""

    # 构建基准约束提示（如果有上传基准文件）
    benchmark_section = ""
    if benchmark_content:
        benchmark_section = f"\n\n===== 质检基准/约束文档 =====\n{benchmark_content[:3000]}\n===== 基准文档结束 =====\n\n请同时参照上述基准文档进行审核：\n- 三元组是否符合基准文档中的定义和约束\n- 实体类型和关系是否与基准一致\n- 是否有违反基准规范的内容"

    results = list(triples)
    for batch_start in range(0, len(results), batch_size):
        batch = results[batch_start:batch_start + batch_size]
        
        triples_text = "\n".join(
            f"{i}. ({t['subject']}, {t['predicate']}, {t['object']}) [原置信度: {t.get('confidence', t.get('llm_confidence', 'N/A'))}]"
            for i, t in enumerate(batch)
        )
        
        user_prompt = f"""原始文本（参考验证）:
{md_content[:3000]}{benchmark_section}

待审核三元组（共{len(batch)}条）:
{triples_text}

请逐条审核。"""

        try:
            response = _call_llm_for_quality(cfg, system_prompt, user_prompt)
            response = re.sub(r"```json\s*", "", response)
            response = re.sub(r"```\s*", "", response)
            start = response.find("[")
            end = response.rfind("]")
            if start >= 0 and end > start:
                reviews = json.loads(response[start:end + 1])
                for r in reviews:
                    idx = r.get("index", 0)
                    # 确保 idx 是 batch 内的局部索引
                    if not (isinstance(idx, int) and 0 <= idx < len(batch)):
                        continue
                    actual_idx = batch_start + idx
                    if actual_idx < len(results):
                        results[actual_idx]["quality_score"] = r.get("quality_score", 50)
                        results[actual_idx]["verdict"] = r.get("verdict", "UNCERTAIN")
                        results[actual_idx]["quality_reason"] = r.get("reason", "")
                        # 更新 confidence 为质检分数
                        results[actual_idx]["confidence"] = r.get("quality_score", 50)
                        results[actual_idx]["llm_confidence"] = r.get("quality_score", 50)
        except Exception:
            continue

    return results


def rule_based_quality(triples: List[Dict]) -> List[Dict]:
    """规则校验：检查基本合理性
    
    规则:
      1. 主语/宾语不能是纯数字
      2. 主语/宾语不能全是标点符号
      3. 主语==宾语但谓语不是自反关系 → 可疑
      4. 单个字符的实体 → 可疑
      5. 纯英文大写缩写 vs 全称 → 可能是别名
    
    Returns:
        增加 reason 字段的三元组列表
    """
    import re
    issues = []

    for i, t in enumerate(triples):
        subj = t.get("subject", "").strip()
        obj = t.get("object", "").strip()
        pred = t.get("predicate", "").strip()

        reasons = []

        # 规则1: 纯数字
        if re.match(r"^\d+$", subj):
            reasons.append("主语为纯数字，可能不完整")
        if re.match(r"^\d+$", obj):
            reasons.append("宾语为纯数字，可能不完整")

        # 规则2: 纯标点/特殊字符
        if re.match(r'^[\s\!\"\#\$\%\&\'\(\)\*\+\,\-\.\/\:\;\<\=\>\?\@\[\]\^\_\`\{\|\}\~\\]+$', subj):
            reasons.append("主语仅为标点符号")
        if re.match(r'^[\s\!\"\#\$\%\&\'\(\)\*\+\,\-\.\/\:\;\<\=\>\?\@\[\]\^\_\`\{\|\}\~\\]+$', obj):
            reasons.append("宾语仅为标点符号")

        # 规则3: 主语=宾语但非自反
        if subj == obj and pred not in [
            "sameAs", "equalTo", "isA", "selfRelation", "hasAlias",
        ]:
            reasons.append(f"主语=宾语但关系为'{pred}'，可能错误")

        # 规则4: 单字符
        if len(subj) <= 1 and not re.match(r"[A-Z]", subj):
            reasons.append("主语仅单字符，实体边界可能不完整")

        if reasons:
            t["rule_check"] = "WARN"
            t["rule_reasons"] = reasons
            # 适当扣分
            current_conf = t.get("confidence", t.get("llm_confidence", 80))
            t["confidence"] = max(0, current_conf - 10 * len(reasons))
            t["llm_confidence"] = t["confidence"]
        else:
            t["rule_check"] = "OK"

    return triples
