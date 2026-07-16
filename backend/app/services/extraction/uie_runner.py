#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UIE 抽取独立运行进程。

隔离原因见 uie_extractor.extract_with_uie 的说明：PaddleNLP(Paddle) 的 Intel OpenMP
(libiomp5) 与 numpy/torch 的 GNU OpenMP(libgomp) 同进程会触发 free(): invalid pointer /
SIGABRT，且该信号 Python 无法捕获。把推理放到本子进程，崩了只杀子进程，worker 不受影响。

用法:
  python -m app.services.extraction.uie_runner '<json_args>'
  json_args = {"md_content", "schemas", "model_name", "threshold", "use_gpu", "gpu_id"}
  成功: 向 stdout 打印一行 JSON {"triples": [...]}
  失败: 向 stdout 打印一行 JSON {"error": "..."} 并以非 0 退出码结束
"""
import sys
import json
import traceback


def main() -> int:
    if len(sys.argv) < 2:
        print(json.dumps({"error": "缺少 args 参数"}))
        return 2
    try:
        args = json.loads(sys.argv[1])
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"error": f"args 解析失败: {e}"}))
        return 2

    try:
        # 直接调用真实实现（避免再走 extract_with_uie 的 subprocess 包装，防止递归）
        from app.services.extraction.uie_extractor import _extract_with_uie_impl
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"error": f"导入 UIE 实现失败: {e}",
                           "trace": traceback.format_exc()}, ensure_ascii=False))
        return 3

    try:
        triples = _extract_with_uie_impl(
            md_content=args.get("md_content", ""),
            schemas=args.get("schemas", []),
            model_name=args.get("model_name", "uie-base"),
            threshold=args.get("threshold", 0.5),
            use_gpu=args.get("use_gpu", False),
            gpu_id=args.get("gpu_id", 0),
        )
        print(json.dumps({"triples": triples}, ensure_ascii=False))
        return 0
    except Exception as e:  # noqa: BLE001
        print(json.dumps({
            "error": f"{type(e).__name__}: {e}",
            "trace": traceback.format_exc(),
        }, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
