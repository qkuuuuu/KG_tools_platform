"""环节①：文档解析 —— 验证 OCR 结果格式化等纯逻辑可正常运行。"""
from app.services.parsers import _format_ocr_result


def test_format_ocr_result_basic():
    # PaddleOCR 返回: [[ [bbox], (text, conf) ], ...]
    result = [
        [
            [[0, 0, 1, 1], ("回转窑", 0.98)],
            [[0, 2, 1, 3], ("是一种设备", 0.95)],
        ]
    ]
    out = _format_ocr_result(result)
    assert out == "回转窑\n是一种设备"


def test_format_ocr_result_empty():
    assert _format_ocr_result([]) == ""
    assert _format_ocr_result(None) == ""
    # 空 page 被跳过
    assert _format_ocr_result([[]]) == ""


def test_format_ocr_result_skips_blank():
    result = [[[ [0, 0, 1, 1], ("  ", 0.9) ], [ [0, 0, 1, 1], ("有效文本", 0.9) ]]]
    out = _format_ocr_result(result)
    assert out == "有效文本"
