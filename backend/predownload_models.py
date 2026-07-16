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
  - GLiNER:       GLiNER.from_pretrained('urchade/gliner_base') -> HF cache
  - DeepKE:       modelscope pipeline(RaNER) -> ModelScope cache
  - MinerU:       mineru models-download (或首次解析时自动下载)

策略: 每个模型独立 try/except，单个失败不阻断构建；失败时打印告警，
运行时对应引擎会回退到「首次使用自动下载」(或降级方案)。
"""
import os
import sys
import time
import subprocess
import tempfile


def log(msg: str):
    print(f"[predownload] {msg}", flush=True)


def run_python_snippet(code: str, retries: int = 1, delay: float = 5.0) -> bool:
    """在子进程中执行一段 Python 片段（触发模型下载），返回是否成功。

    为什么走子进程而非 exec:
      某些推理框架(PaddlePaddle 等)在 import/初始化阶段可能触发 C 层
      SIGABRT(free(): invalid pointer 等)。这种信号 Python 的 try/except
      捕获不到, 会直接杀掉当前进程 → 整次镜像构建失败。放到子进程执行后,
      父进程只检查子进程返回码, 单个模型崩溃不会中断其它模型下载 / 构建。

    retries: 失败重试次数（应对 HF / ModelScope 偶发网络抖动，如 RemoteDisconnected）。
    """
    fd, path = tempfile.mkstemp(suffix=".py", prefix="predl_")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(code + "\n")
        for attempt in range(1, retries + 1):
            try:
                # 继承父进程环境(HOME/HF_ENDPOINT 等由 Dockerfile ENV 注入),
                # 子进程 stdout/stderr 直接继承, 便于实时看到下载进度。
                proc = subprocess.run([sys.executable, path], check=False)
                if proc.returncode == 0:
                    return True
                log(f"  失败(第{attempt}/{retries}次): 子进程退出码 {proc.returncode}")
            except Exception as e:  # noqa: BLE001
                log(f"  失败(第{attempt}/{retries}次): {e}")
            if attempt < retries:
                log(f"  {delay}s 后重试…")
                time.sleep(delay)
        return False
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def run_cmd(cmd, retries: int = 1, delay: float = 5.0, input_data: bytes = None) -> bool:
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            # 默认 stdin=DEVNULL：避免交互命令在无 TTY 的构建环境里卡死整个构建；
            # 若传入 input_data（如给 mineru-models-download 喂入模型源选择），则改用该
            # 输入使其非交互完成（MINERU_MODEL_SOURCE 在该版本仍会交互询问，故显式喂入）。
            # 注意：不能同时传 stdin 与 input —— input 隐含 stdin=PIPE，二者叠加会抛
            # "stdin and input arguments may not both be used"。故按是否提供 input_data 二选一。
            if input_data is not None:
                subprocess.run(cmd, check=True, input=input_data)
            else:
                subprocess.run(cmd, check=True, stdin=subprocess.DEVNULL)
            return True
        except Exception as e:  # noqa: BLE001
            last_err = e
            log(f"  失败(第{attempt}/{retries}次): {e}")
            if attempt < retries:
                log(f"  {delay}s 后重试…")
                time.sleep(delay)
    return False


def main():
    log(f"开始预下载模型，缓存根目录 = {os.path.expanduser('~')}")
    log(f"HF_ENDPOINT = {os.environ.get('HF_ENDPOINT', '(未设置)')}")
    log(f"MINERU_MODEL_SOURCE = {os.environ.get('MINERU_MODEL_SOURCE', '(未设置)')}")

    # 1) spaCy 英文 + 中文小模型（GLiNER / UIE 降级方案需要）
    # 注：模型统一在 Dockerfile 的 pip 层(pip install zh-core-web-sm / en-core-web-sm，
    # 走 PyPI 清华镜像)预装，【不再用 python -m spacy download】——后者默认从
    # GitHub Releases 拉 wheel，国内极慢易 ReadTimeout，是构建卡死的主因。
    # 这里只做可用性校验，不联网。
    log("1/6 spaCy en_core_web_sm / zh_core_web_sm")
    import importlib
    spacy_mod = importlib.import_module("spacy")
    for m in ["en_core_web_sm", "zh_core_web_sm"]:
        try:
            spacy_mod.load(m)
            log(f"  OK {m}")
        except Exception as e:  # noqa: BLE001
            log(f"  !! {m} 不可用: {e}")

    # 2) PaddleOCR PP-OCRv4 (检测/识别/方向分类)
    log("2/6 PaddleOCR PP-OCRv4")
    if run_python_snippet(
        "from paddleocr import PaddleOCR; "
        "PaddleOCR(use_angle_cls=True, lang='ch', use_gpu=False)",
        retries=2,
    ):
        log("  OK PaddleOCR")
    else:
        log("  !! PaddleOCR 下载失败（运行时首次解析会自动下载）")

    # 3) UIE (PaddleNLP) uie-base-zh
    log("3/6 UIE uie-base-zh")
    if run_python_snippet(
        "from paddlenlp import Taskflow; "
        "Taskflow('information_extraction', schema=['人物', '组织'], "
        "model='uie-base-zh', device='cpu')",
        retries=2,
    ):
        log("  OK UIE")
    else:
        log("  !! UIE 下载失败（运行时首次使用会自动下载）")

    # 4) GLiNER 多语言零样本 NER（走 HF 镜像，偶发网络断开，加重试）
    # 注意：原 urchade/gliner_multilingual 已是 gated 仓库，hf-mirror 不支持 gated 鉴权会 401；
    # 改用非 gated 的 urchade/gliner_base（同 API，GLiNER.from_pretrained 直接兼容）。
    log("4/6 GLiNER urchade/gliner_base")
    if run_python_snippet(
        "from gliner import GLiNER; "
        "GLiNER.from_pretrained('urchade/gliner_base')",
        retries=4,
        delay=10.0,
    ):
        log("  OK GLiNER")
    else:
        log("  !! GLiNER 下载失败（运行时首次使用会自动下载）")

    # 5) DeepKE / ModelScope RaNER 中文通用 NER（走 ModelScope，加重试）
    log("5/6 DeepKE ModelScope RaNER")
    if run_python_snippet(
        "from modelscope.pipelines import pipeline; "
        "from modelscope.utils.constant import Tasks; "
        "pipeline(Tasks.named_entity_recognition, "
        "model='iic/nlp_raner_named-entity-recognition_chinese-base-generic')",
        retries=3,
    ):
        log("  OK DeepKE")
    else:
        log("  !! DeepKE 下载失败（运行时首次使用会自动下载）")

    # 6) MinerU 版面 / 公式 / 表格模型
    # 注：MinerU 3.x 的下载命令是 `mineru-models-download`（连字符，独立可执行文件），
    # 不是 `mineru models-download`（空格子命令，旧写法已不存在）。
    # 该命令在无 TTY 时会交互询问模型源(auto/huggingface/modelscope)，即便已设
    # MINERU_MODEL_SOURCE=modelscope 仍会问，故显式喂入 "modelscope\n" 非交互选定。
    # 依次尝试两种写法，命中其一即视为成功。
    log("6/6 MinerU 模型")
    mineru_ok = False
    for mineru_cmd in (["mineru-models-download"], ["mineru", "models-download"]):
        if run_cmd(mineru_cmd, retries=3, delay=10.0, input_data=b"modelscope\n"):
            mineru_ok = True
            break
    if mineru_ok:
        log("  OK MinerU models-download")
    else:
        log("  !! MinerU models-download 不支持或失败"
            "（运行时首次解析会自动下载）")

    log("预下载流程结束。"
        "（部分模型失败不影响镜像构建，运行时对应引擎会自动回退下载。）")
    sys.exit(0)


if __name__ == "__main__":
    main()
