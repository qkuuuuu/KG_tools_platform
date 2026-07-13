#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""镜像构建期预下载所有大模型，避免用户首次使用时联网下载。

缓存目录统一指向 /opt/models（由 Dockerfile 通过 HOME / HF_HOME / MODELSCOPE_CACHE
/ PADDLENLP_HOME 等环境变量指定）。运行时服务进程继承同一套环境变量，
因此能直接命中构建期已下载的模型，无需再次下载。

各引擎下载触发方式:
  - spaCy:        python -m spacy download <model>
  - PaddleOCR:    PaddleOCR(use_angle_cls=True, lang='ch')  -> ~/.paddleocr
  - UIE(PaddleNLP): Taskflow('information_extraction', model='uie-base-zh') -> ~/.paddlenlp
  - GLiNER:       GLiNER.from_pretrained('urchade/gliner_multilingual') -> HF cache
  - DeepKE:       modelscope pipeline(RaNER) -> ModelScope cache
  - MinerU:       mineru models-download (或首次解析时自动下载)

策略: 每个模型独立 try/except，单个失败不阻断构建；失败时打印告警，
运行时对应引擎会回退到「首次使用自动下载」(或降级方案)。
"""
import os
import sys
import subprocess
import traceback


def log(msg: str):
    print(f"[predownload] {msg}", flush=True)


def run_python_snippet(code: str) -> bool:
    """执行一段 Python 片段（用于触发模型下载），返回是否成功。"""
    try:
        exec(compile(code, "<predownload>", "exec"))
        return True
    except Exception as e:  # noqa: BLE001
        log(f"  失败: {e}")
        traceback.print_exc()
        return False


def run_cmd(cmd) -> bool:
    try:
        subprocess.run(cmd, check=True)
        return True
    except Exception as e:  # noqa: BLE001
        log(f"  失败: {e}")
        return False


def main():
    log(f"开始预下载模型，缓存根目录 = {os.path.expanduser('~')}")
    log(f"HF_ENDPOINT = {os.environ.get('HF_ENDPOINT', '(未设置)')}")
    log(f"MINERU_MODEL_SOURCE = {os.environ.get('MINERU_MODEL_SOURCE', '(未设置)')}")

    # 1) spaCy 英文 + 中文小模型（GLiNER / UIE 降级方案需要）
    log("1/6 spaCy en_core_web_sm / zh_core_web_sm")
    for m in ["en_core_web_sm", "zh_core_web_sm"]:
        if run_cmd([sys.executable, "-m", "spacy", "download", m]):
            log(f"  OK {m}")
        else:
            log(f"  !! {m} 下载失败（运行时将自动回退到规则抽取）")

    # 2) PaddleOCR PP-OCRv4 (检测/识别/方向分类)
    log("2/6 PaddleOCR PP-OCRv4")
    if run_python_snippet(
        "from paddleocr import PaddleOCR; "
        "PaddleOCR(use_angle_cls=True, lang='ch', use_gpu=False)"
    ):
        log("  OK PaddleOCR")
    else:
        log("  !! PaddleOCR 下载失败（运行时首次解析会自动下载）")

    # 3) UIE (PaddleNLP) uie-base-zh
    log("3/6 UIE uie-base-zh")
    if run_python_snippet(
        "from paddlenlp import Taskflow; "
        "Taskflow('information_extraction', schema=['人物', '组织'], "
        "model='uie-base-zh', device='cpu')"
    ):
        log("  OK UIE")
    else:
        log("  !! UIE 下载失败（运行时首次使用会自动下载）")

    # 4) GLiNER 多语言零样本 NER
    log("4/6 GLiNER urchade/gliner_multilingual")
    if run_python_snippet(
        "from gliner import GLiNER; "
        "GLiNER.from_pretrained('urchade/gliner_multilingual')"
    ):
        log("  OK GLiNER")
    else:
        log("  !! GLiNER 下载失败（运行时首次使用会自动下载）")

    # 5) DeepKE / ModelScope RaNER 中文通用 NER
    log("5/6 DeepKE ModelScope RaNER")
    if run_python_snippet(
        "from modelscope.pipelines import pipeline; "
        "from modelscope.utils.constant import Tasks; "
        "pipeline(Tasks.named_entity_recognition, "
        "model='iic/nlp_raner_named-entity-recognition_chinese-base-generic')"
    ):
        log("  OK DeepKE")
    else:
        log("  !! DeepKE 下载失败（运行时首次使用会自动下载）")

    # 6) MinerU 版面 / 公式 / 表格模型
    log("6/6 MinerU 模型")
    if run_cmd(["mineru", "models-download"]):
        log("  OK MinerU models-download")
    else:
        log("  !! MinerU models-download 不支持或失败"
            "（运行时首次解析会自动下载）")

    log("预下载流程结束。"
        "（部分模型失败不影响镜像构建，运行时对应引擎会自动回退下载。）")
    sys.exit(0)


if __name__ == "__main__":
    main()
