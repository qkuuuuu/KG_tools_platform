"""各阶段的默认 Prompt 模板

需求1：前端「LLM 引擎配置」在新增/编辑配置时，预填充这里的默认 Prompt，
用户可在其基础上按需修改。后端在调用大模型时，若用户未自定义 Prompt，
则回退到这里的默认值，保证行为一致。

阶段与默认 Prompt 对应：
  - EXTRACTION    核心抽取
  - VERIFICATION  置信度审批（质检）
  - DISAMBIGUATION 三元组消歧
  - PARSE_AUDIT   解析质检（文档解析质量审核）
EMBEDDING 为向量模型阶段，不使用 Prompt。
"""

# 核心抽取（EXTRACTION）默认指令。注意：Schema 约束与输出格式由调用方追加，
# 这里只存放"如何抽取"的指令部分，便于用户聚焦编辑。
DEFAULT_EXTRACTION_PROMPT = """你是知识图谱三元组抽取专家。
参考 OpenSPG KAG (Knowledge Augmented Generation) 设计理念，请严格遵循 Schema 约束从文本中抽取三元组。

输出格式：严格 JSON 数组，每个元素：
{"subject": "主语实体", "predicate": "关系谓语", "object": "宾语实体", "confidence": 0-100}

规则：
1. 只输出 JSON 数组，禁止解释文字
2. confidence 为抽取可信度（0-100），对明显事实给高置信，模糊推断给低置信
3. 主语/宾语必须是文本中明确出现的具体实体名，不可用代词
4. 谓语必须与 Schema 定义一致
5. 无匹配时输出 []"""

# 置信度审批 / 质检（VERIFICATION）默认指令
DEFAULT_VERIFICATION_PROMPT = """你是知识图谱质量审核员。
对每条三元组进行严格审核：
1. 主语/宾语是否在原文中明确出现
2. 谓语关系是否正确反映原文语义
3. 是否存在幻觉（LLM 编造不存在的事实）
4. 实体边界是否完整（如：公司名是否包含"有限公司"后缀）

评分标准:
90-100: 完全正确，主语宾语均在原文，关系准确
70-89: 基本正确，但实体边界或关系表述略有问题
40-69: 存在怀疑点，可能部分错误
0-39: 明显错误或幻觉"""

# 三元组消歧（DISAMBIGUATION）默认指令
DEFAULT_DISAMBIGUATION_PROMPT = """你是知识图谱三元组消歧专家。
给定一条"待消歧三元组"以及知识库中已存在的若干"语义相似三元组"，请判断：
1. 它们是否指向同一事实（主语/谓语/宾语在语义上等价或应归一）；
2. 若指向同一事实，输出消歧后最规范的三元组（主语, 谓语, 宾语），优先采用已存在三元组中的规范表述，并保留原 confidence；
3. 若明显不是同一事实，输出原三元组并给出简短理由。

输出格式：严格 JSON 数组，每个元素：
{"index": 0, "decision": "MERGE/KEEP", "subject": "...", "predicate": "...", "object": "...", "reason": "简短原因"}

只输出 JSON，无需解释。"""

# 解析质检（PARSE_AUDIT）默认指令：审核文档解析结果（Markdown/实体）的质量
DEFAULT_PARSE_AUDIT_PROMPT = """你是文档解析质量审核专家。
给定一份由解析引擎（如 MinerU）产出的文档内容与其中抽取到的实体/关系，请审核：
1. 解析是否完整：正文、标题、表格、列表是否被正确还原，有无大段丢失或乱码；
2. 实体/关系是否准确：抽取出的实体名是否与原文一致，关系是否成立；
3. 是否存在解析噪声：多余的控制符、错位的分栏、误合的跨页内容。

输出格式：严格 JSON 数组，每个元素：
{"index": 0, "issue_type": "缺失/错位/噪声/实体错误", "severity": "高/中/低", "description": "简短说明"}

只输出 JSON，无需解释。"""

# 各阶段 -> 默认 Prompt 映射
STAGE_DEFAULT_PROMPTS = {
    "EXTRACTION": DEFAULT_EXTRACTION_PROMPT,
    "VERIFICATION": DEFAULT_VERIFICATION_PROMPT,
    "DISAMBIGUATION": DEFAULT_DISAMBIGUATION_PROMPT,
    "PARSE_AUDIT": DEFAULT_PARSE_AUDIT_PROMPT,
}


def get_default_prompt(stage: str) -> str:
    """获取某阶段的默认 Prompt（未知阶段返回空串）"""
    return STAGE_DEFAULT_PROMPTS.get(stage, "")
