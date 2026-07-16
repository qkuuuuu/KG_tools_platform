#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PaddleOCR 独立运行进程。

为什么独立成子进程:
  Paddle 使用 Intel OpenMP(libiomp5)，而 numpy/opencv/torch 使用 GNU OpenMP(libgomp)。
  两者同进程加载会触发 free(): invalid pointer / SIGABRT，且 SIGABRT 是 C 层信号，
  Python 无法捕获，会直接杀掉宿主进程(即 FastAPI worker)。
  把 PaddleOCR 推理放在本独立子进程里执行：即使崩溃也只杀子进程，
  worker 通过返回码/JSON 拿到结果或错误，自身不受影响，其它引擎照常工作。

用法:
  python paddleocr_runner.py <input_path>
  成功: 向 stdout 打印一行 JSON {"content": "...", "score": 80.0}
  失败: 向 stdout 打印一行 JSON {"error": "..."} 并以非 0 退出码结束
"""
import os
import sys
import json
import traceback


def _format_ocr_result(result) -> str:
    """将 PaddleOCR 结果格式化为纯文本。

    PaddleOCR 返回格式: [[ [bbox], (text, confidence) ], ...]
    """
    lines = []
    if not result:
        return ""
    for page in result:
        if not page:
            continue
        for line in page:
            if line and len(line) >= 2:
                text = line[1][0] if isinstance(line[1], tuple) else str(line[1])
                if text.strip():
                    lines.append(text)
    return "\n".join(lines)


def main() -> int:
    if len(sys.argv) < 2:
        print(json.dumps({"error": "缺少输入文件路径参数"}))
        return 2

    file_path = sys.argv[1]
    # 预下载的 PaddleOCR 模型缓存在 HOME=/opt/models/.paddleocr（由 Dockerfile ENV 注入），
    # 子进程继承父进程环境变量即可命中，无需重新下载。
    try:
        import fitz  # PyMuPDF：PDF 页面转图片（自带 C++ 实现，不依赖 libgomp）
        from paddleocr import PaddleOCR
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"error": f"导入 PaddleOCR/PyMuPDF 失败: {e}"}))
        return 3

    try:
        ocr = PaddleOCR(use_angle_cls=True, lang='ch', show_log=False)
        parts = []
        ext = os.path.splitext(file_path)[1].lower()

        if ext == '.pdf':
            doc = fitz.open(file_path)
            for i, page in enumerate(doc, 1):
                pix = page.get_pixmap(dpi=200)
                img_path = file_path + f"_page_{i}.png"
                pix.save(img_path)
                try:
                    result = ocr.ocr(img_path, cls=True)
                    text = _format_ocr_result(result)
                    if text.strip():
                        parts.append(f"## Page {i}\n\n{text}\n")
                finally:
                    if os.path.exists(img_path):
                        os.remove(img_path)
            doc.close()
        else:
            result = ocr.ocr(file_path, cls=True)
            text = _format_ocr_result(result)
            if text.strip():
                parts.append(text)

        content = "\n".join(parts)
        score = 80.0 if content else 30.0
        print(json.dumps({"content": content, "score": score}, ensure_ascii=False))
        return 0
    except Exception as e:  # noqa: BLE001
        print(json.dumps({
            "error": f"{type(e).__name__}: {e}",
            "trace": traceback.format_exc(),
        }, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
