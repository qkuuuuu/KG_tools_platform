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


# ---------------------------------------------------------------------------
# 质检评分 / verdict 归一化辅助（对齐 DEFAULT_VERIFICATION_PROMPT 的评分标准）
# ---------------------------------------------------------------------------

# 评分区间（与 VERIFICATION 评分标准保持一致）：
#   90-100 完全正确；70-89 基本正确；40-69 存在怀疑点；0-39 明显错误/幻觉
_SCORE_PASS_FLOOR = 90.0
_SCORE_BASIC_CORRECT_FLOOR = 70.0
_SCORE_REJECT_FLOOR = 40.0

# verdict 别名归一化（兼容 LLM 返回中文 / 大小写不一致）
_VERDICT_ALIASES = {
    "pass": "PASS", "通过": "PASS", "正确": "PASS", "true": "PASS",
    "reject": "REJECT", "拒绝": "REJECT", "不通过": "REJECT", "错误": "REJECT", "false": "REJECT",
    "uncertain": "UNCERTAIN", "待定": "UNCERTAIN", "不确定": "UNCERTAIN", "存疑": "UNCERTAIN",
}


def _coerce_score(value, default: float = 50.0) -> float:
    """把 LLM 返回的 quality_score 转成受限于 [0,100] 的 float。

    历史缺陷：原始实现直接 ``r.get("quality_score", 50)``，若模型返回字符串
    （如 ``"88"``）或越界值，下游 ``score >= threshold`` 比较会出错 / 误判。
    """
    if isinstance(value, bool):
        return float(default)
    if isinstance(value, (int, float)):
        try:
            s = float(value)
        except (TypeError, ValueError):
            return float(default)
    else:
        try:
            s = float(str(value).strip())
        except (TypeError, ValueError):
            return float(default)
    return max(0.0, min(100.0, s))


def _normalize_verdict(verdict_raw, score: float) -> str:
    """归一化 LLM 返回的 verdict。

    - 显式 ``REJECT``（含中文「拒绝/不通过/错误」）始终尊重：视为幻觉 / 明显错误，拒绝入库；
    - 其余（PASS / UNCERTAIN / 缺失 / 无法识别）统一按评分区间推导，确保与
      VERIFICATION 评分标准一致：基本正确(>=70) → PASS；怀疑(40-69) → UNCERTAIN；错误(<40) → REJECT。

    历史缺陷：原始实现要求 LLM 必须显式返回 ``"PASS"`` 才算通过，且 ``llm_quality_review``
    的 system_prompt 又规定「评分 < 90 视为待定(UNCERTAIN)」，二者自相矛盾。结果是大量
    「基本正确」（评分 70-89，LLM 据此返回 UNCERTAIN）的三元组既非 PASS 也非 REJECT，
    只能停留在 PENDING（人工待审），最终表现为极低通过率（如线上观察到的 490→40）。
    修复：凡评分属于「基本正确」区间即视为通过。
    """
    explicit = None
    if verdict_raw is not None:
        key = str(verdict_raw).strip().lower()
        if key in _VERDICT_ALIASES:
            explicit = _VERDICT_ALIASES[key]
    # 显式拒绝始终尊重（幻觉 / 明显错误）
    if explicit == "REJECT":
        return "REJECT"
    # 其余按评分区间推导（对齐评分标准：70-89 基本正确 -> 通过）
    if score >= _SCORE_BASIC_CORRECT_FLOOR:
        return "PASS"
    if score >= _SCORE_REJECT_FLOOR:
        return "UNCERTAIN"
    return "REJECT"


def llm_quality_review(
    triples: List[Dict],
    md_content: str,
    cfg: Dict,
    threshold: float = 90.0,
    batch_size: int = 15,
    benchmark_content: str = "",
    custom_prompt: str = None,
    schema_list: List[Dict] = None,
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
        custom_prompt: 用户自定义质检 Prompt（需求3），覆盖默认指令
        schema_list: 项目约束表（需求3），作为审核上下文一并发送给大模型
    
    Returns:
        更新后的三元组（新增 quality_score, verdict, reason）
    """
    if not triples:
        return []

    from app.services.default_prompts import DEFAULT_VERIFICATION_PROMPT
    instruction = (custom_prompt.strip() if custom_prompt and custom_prompt.strip()
                   else DEFAULT_VERIFICATION_PROMPT)

    system_prompt = f"""{instruction}

输出格式: JSON 数组:
[{{"index": 0, "quality_score": 0-100, "verdict": "PASS/REJECT/UNCERTAIN", "reason": "简短原因"}}]

通过阈值: 评分 >= {threshold} 视为通过(PASS)；明显错误或幻觉视为拒绝(REJECT)；其余为待定(UNCERTAIN)。

只输出 JSON，无需解释。"""

    # 构建基准约束提示（如果有上传基准文件，需求3）
    benchmark_section = ""
    if benchmark_content:
        benchmark_section = f"\n\n===== 质检基准/约束文档 =====\n{benchmark_content[:3000]}\n===== 基准文档结束 =====\n\n请同时参照上述基准文档进行审核：\n- 三元组是否符合基准文档中的定义和约束\n- 实体类型和关系是否与基准一致\n- 是否有违反基准规范的内容"

    # 构建约束表提示（需求3：将约束表一并发送给大模型）
    schema_section = ""
    if schema_list:
        schema_desc = "\n".join(
            f"- {s.get('subject_label') or s.get('subject_type')} --[{s.get('predicate_label') or s.get('predicate')}]--> {s.get('object_label') or s.get('object_type')}"
            for s in schema_list[:50]
        )
        schema_section = f"\n\n===== 项目约束表（Schema） =====\n{schema_desc}\n===== 约束表结束 =====\n\n请同时参照上述约束表审核：实体类型与关系是否符合约束定义。"

    results = list(triples)
    for batch_start in range(0, len(results), batch_size):
        batch = results[batch_start:batch_start + batch_size]
        
        triples_text = "\n".join(
            f"{i}. ({t['subject']}, {t['predicate']}, {t['object']}) [原置信度: {t.get('confidence', t.get('llm_confidence', 'N/A'))}]"
            for i, t in enumerate(batch)
        )
        
        user_prompt = f"""原始文本（参考验证）:
{md_content[:3000]}{benchmark_section}{schema_section}

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
            else:
                reviews = []
        except Exception:
            reviews = []

        # 建立 index -> review 映射；兼容 1-based、缺失 index、越界 index：
        #  - 历史缺陷：``r.get("index", 0)`` 在 index 缺失时默认 0，会把多条 review 错误覆盖到
        #    第 0 条；且 ``0 <= idx < len(batch)`` 会直接丢弃 idx == len(batch) 的末条（常见于
        #    LLM 用 1-based 编号），造成整批评分错位 / 漏评，最终大量三元组拿不到有效 verdict。
        indexed, unindexed = [], []
        for r in reviews:
            if not isinstance(r, dict):
                continue
            raw = r.get("index", None)
            if raw is None:
                unindexed.append(r)
            else:
                try:
                    indexed.append((int(raw), r))
                except (TypeError, ValueError):
                    unindexed.append(r)

        # 判定 1-based：若所有带 index 的评审最大编号 == len(batch)（0-based 下最大应为 len-1），
        # 则可判定 LLM 采用了 1-based 编号，整体偏移 -1。
        if indexed:
            max_idx = max(i for i, _ in indexed)
            min_idx = min(i for i, _ in indexed)
            offset = -1 if (max_idx == len(batch) and min_idx >= 1) else 0
        else:
            offset = 0

        by_pos = {}
        for raw, r in indexed:
            pos = raw + offset
            if 0 <= pos < len(batch):
                by_pos[pos] = r  # 后者覆盖前者

        # 缺失 index 的评审，按出现顺序填入尚未被占用的位置
        free = [p for p in range(len(batch)) if p not in by_pos]
        for r, p in zip(unindexed, free):
            by_pos[p] = r

        for pos, r in by_pos.items():
            actual_idx = batch_start + pos
            if actual_idx >= len(results):
                continue
            score = _coerce_score(r.get("quality_score"))
            verdict = _normalize_verdict(r.get("verdict"), score)
            results[actual_idx]["quality_score"] = score
            results[actual_idx]["verdict"] = verdict
            results[actual_idx]["quality_reason"] = r.get("reason", "")
            # 更新 confidence 为质检分数
            results[actual_idx]["confidence"] = score
            results[actual_idx]["llm_confidence"] = score

        # 兜底：本批次未匹配到任何 review 的三元组，写入原始置信度并派生 verdict，
        # 避免下游（路由 PASS/FAIL 判定）因缺失字段而 KeyError 或误判为低分。
        for pos in range(len(batch)):
            actual_idx = batch_start + pos
            if actual_idx >= len(results):
                break
            t = results[actual_idx]
            if "quality_score" not in t:
                base = _coerce_score(t.get("confidence", t.get("llm_confidence", 50.0)))
                t["quality_score"] = base
                t["verdict"] = _normalize_verdict(None, base)
                t["quality_reason"] = t.get("quality_reason", "")
                t["confidence"] = base
                t["llm_confidence"] = base

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

        # 规则2: 纯标点/特殊字符（兼容 ASCII 与全角/CJK 标点）
        _punct_ascii = r'^[\s\!\"\#\$\%\&\'\(\)\*\+\,\-\.\/\:\;\<\=\>\?\@\[\]\^\_\`\{\|\}\~\\]+$'
        _punct_cjk = r'^[\s\u3000-\u303f\uff00-\uffef]+$'
        if re.match(_punct_ascii, subj) or re.match(_punct_cjk, subj):
            reasons.append("主语仅为标点符号")
        if re.match(_punct_ascii, obj) or re.match(_punct_cjk, obj):
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
