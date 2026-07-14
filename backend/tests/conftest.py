"""pytest 公共 fixtures —— 让 KG 平台各「环节」在离线环境（不装 paddle/torch/gliner…）下可单测。

核心策略：
- 所有重型模型库在业务代码里都是「函数内惰性 import」，所以模块本身能 import。
- 需要调模型的地方，用 monkeypatch 把各入口的 _call_llm* 换成假实现（"欺骗"模型调用）。
- DB 用轻量 FakeSession（实现 query/filter/all/first/delete/add/commit），不连真库。
"""
import os

# 测试期间使用 sqlite，避免 create_engine 在导入期 eager 加载 psycopg2、
# 也避免 _run_additive_migrations 去连 Postgres 网络（非 postgres 方言会 early-return）。
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_kg.db")

import operator

import pytest


# ---------------------------------------------------------------------------
# 假 LLM / DB 基础设施
# ---------------------------------------------------------------------------

class FakeQuery:
    """极简 SQLAlchemy 查询替身：支持连续 .filter()，按 == 与 in_() 过滤。"""

    def __init__(self, session, model):
        self.session = session
        self.model = model
        self._filters = []

    def filter(self, *conds):
        self._filters.extend(conds)
        return self

    def _match(self, row):
        for c in self._filters:
            try:
                left = getattr(c, "left", None)
                right = getattr(c, "right", None)
                if left is None or right is None:
                    continue
                attr = getattr(left, "key", None) or getattr(left, "name", None)
                left_val = getattr(row, attr, None) if attr else None

                # in_() 操作符
                if OP_IN is not None and c.operator is OP_IN:
                    right_val = getattr(right, "value", right)
                    if not isinstance(right_val, (list, tuple, set)):
                        right_val = [right_val]
                    return left_val in right_val

                right_val = getattr(right, "value", right)
                if c.operator is operator.eq:
                    if not (left_val == right_val):
                        return False
                elif c.operator is operator.ne:
                    if not (left_val != right_val):
                        return False
                else:
                    if not (left_val == right_val):
                        return False
            except Exception:
                return False
        return True

    def all(self):
        rows = self.session._store.get(self.model, [])
        return [r for r in rows if self._match(r)]

    def first(self):
        rows = self.all()
        return rows[0] if rows else None

    def delete(self):
        rows = self.all()
        store = self.session._store.get(self.model, [])
        remaining = [r for r in store if r not in rows]
        self.session._store[self.model] = remaining
        return len(store) - len(remaining)


class FakeSession:
    """极简 DB session 替身。"""

    def __init__(self, data=None):
        self._store = {}
        if data:
            for model, rows in data.items():
                self._store[model] = list(rows)
        self.added = []
        self.committed = 0

    def query(self, model):
        return FakeQuery(self, model)

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        for obj in self.added:
            self._store.setdefault(type(obj), []).append(obj)
        self.added = []
        self.committed += 1

    def refresh(self, obj):
        pass


# 解析 SQLAlchemy 的 in_ 操作符对象（用于 FakeQuery 识别 in_ 过滤）
try:
    from sqlalchemy import sql

    OP_IN = sql.operators.in_op
except Exception:  # pragma: no cover
    OP_IN = None


@pytest.fixture
def fake_session():
    """返回一个空的假 DB session。"""
    return FakeSession()


@pytest.fixture
def cfg():
    """假 LLM 配置（含 api_key，使质检/助手代码认为已配置模型）。"""
    return {
        "api_key": "fake-key",
        "base_url": "http://fake",
        "model_name": "fake-model",
        "api_provider": "OPENAI",
    }


# 假 LLM 返回样例 ----------------------------------------------------------

# 抽取环节：假 LLM 返回的三元组 JSON（实体必须出现在测试文本中，否则事实核查会丢弃）
SAMPLE_LLM_TRIPLES_JSON = (
    '[{"subject": "回转窑", "predicate": "hasFault", "object": "故障", "confidence": 92}]'
)

# 质检环节：假 LLM 返回的审核结果
SAMPLE_QUALITY_JSON = (
    '[{"index": 0, "quality_score": 95, "verdict": "PASS", "reason": "原文明确出现"}]'
)

# 融合消歧环节：假 LLM 返回的判断
SAMPLE_FUSION_JSON = (
    '[{"index": 0, "decision": "MERGE", "reason": "同一实体别名"}]'
)


@pytest.fixture
def patch_llm_engine(monkeypatch):
    """欺骗 llm_engine 的 _call_llm / _get_llm_config。"""
    monkeypatch.setattr(
        "app.services.llm_engine._call_llm",
        lambda cfg, sp, up, temperature=0.1: "FAKE_LLM_ANSWER",
    )
    monkeypatch.setattr(
        "app.services.llm_engine._get_llm_config",
        lambda db, pid, stage=None: {
            "api_key": "fake-key",
            "base_url": "http://fake",
            "model_name": "fake-model",
            "api_provider": "OPENAI",
        },
    )


@pytest.fixture
def patch_llm_extractor(monkeypatch):
    """欺骗 LLM 抽取器的 _call_llm，返回固定三元组 JSON。"""
    monkeypatch.setattr(
        "app.services.extraction.llm_extractor._call_llm",
        lambda cfg, sp, up, temperature=0.1: SAMPLE_LLM_TRIPLES_JSON,
    )


@pytest.fixture
def patch_quality_llm(monkeypatch):
    """欺骗质检的 _call_llm_for_quality。"""
    monkeypatch.setattr(
        "app.services.quality._call_llm_for_quality",
        lambda cfg, sp, up: SAMPLE_QUALITY_JSON,
    )


@pytest.fixture
def patch_fusion_llm(monkeypatch):
    """欺骗融合消歧的 _call_llm_for_fusion。"""
    monkeypatch.setattr(
        "app.services.fusion.llm_fusion._call_llm_for_fusion",
        lambda cfg, sp, up: SAMPLE_FUSION_JSON,
    )


# ---------------------------------------------------------------------------
# 样例数据 fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def schemas():
    """一组「实体-关系-实体」Schema 约束（水泥领域）。"""
    return [
        {
            "subject_type": "Equipment",
            "subject_label": "设备",
            "predicate": "hasComponent",
            "predicate_label": "包含部件",
            "object_type": "EquipmentComponent",
            "object_label": "设备部件",
        },
        {
            "subject_type": "EquipmentComponent",
            "subject_label": "设备部件",
            "predicate": "componentOf",
            "predicate_label": "属于设备",
            "object_type": "Equipment",
            "object_label": "设备",
        },
        {
            "subject_type": "Symptom",
            "subject_label": "征兆",
            "predicate": "infersFaultMode",
            "predicate_label": "推断出故障模式",
            "object_type": "FaultMode",
            "object_label": "故障模式",
        },
    ]


@pytest.fixture
def triples():
    """一组样例三元组（用于导出/融合测试）。"""
    return [
        {
            "subject": "回转窑",
            "predicate": "包含部件",
            "object": "托轮",
            "subject_type": "设备",
            "object_type": "设备部件",
            "confidence": 90,
            "extraction_method": "LLM_PROMPT",
        },
        {
            "subject": "托轮",
            "predicate": "属于设备",
            "object": "回转窑",
            "subject_type": "设备部件",
            "object_type": "设备",
            "confidence": 85,
            "extraction_method": "LLM_PROMPT",
        },
    ]
