"""环节⑥：动态 Schema 定义 —— DSL 解析（纯逻辑）+ 约束写入（假 DB）。"""
import pytest

from app.services.schema_dsl import parse_dsl, save_schema_constraints
from app.models import SchemaConstraint


SAMPLE_DSL = """
namespace Cement1

Equipment(设备): EntityType
    relations:
        hasComponent(包含部件): EquipmentComponent

EquipmentComponent(设备部件): EntityType
    relations:
        componentOf(属于设备): Equipment
"""


def test_parse_dsl_namespace_and_entities():
    result = parse_dsl(SAMPLE_DSL)
    assert result["namespace"] == "Cement1"
    names = {e["name"] for e in result["entities"]}
    assert "Equipment" in names
    assert "EquipmentComponent" in names


def test_parse_dsl_relations_have_chinese_labels():
    result = parse_dsl(SAMPLE_DSL)
    assert len(result["relations"]) >= 2
    r = result["relations"][0]
    assert r["subject_label"] == "设备"
    assert r["predicate_label"] == "包含部件"
    assert r["object_label"] == "设备部件"


def test_parse_dsl_empty():
    out = parse_dsl("")
    assert out["error"]
    assert out["entities"] == []
    assert out["relations"] == []


def test_save_schema_constraints_clears_then_writes(fake_session):
    relations = [
        {
            "subject_type": "Equipment",
            "subject_label": "设备",
            "predicate": "hasComponent",
            "predicate_label": "包含部件",
            "object_type": "EquipmentComponent",
            "object_label": "设备部件",
        }
    ]
    # 预置一条旧约束，验证会被清空
    class _Old:
        project_id = "p1"

    fake_session._store[SchemaConstraint] = [_Old()]
    save_schema_constraints(fake_session, "p1", relations)
    stored = fake_session._store.get(SchemaConstraint, [])
    assert len(stored) == 1
    assert stored[0].subject_type == "Equipment"
    assert stored[0].predicate == "hasComponent"
    assert stored[0].project_id == "p1"
