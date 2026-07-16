"""文档解析引擎 - 真实实现
支持: pdfplumber / PyMuPDF / python-docx / PaddleOCR / MinerU / 纯文本 / CSV / Excel
"""
import os
import re
import time
import json
import logging
import tempfile
import subprocess
import shutil
from typing import Tuple

logger = logging.getLogger(__name__)


def parse_with_pdfplumber(file_path: str) -> Tuple[str, float]:
    """用 pdfplumber 解析 PDF，返回 (markdown, 质量评分)"""
    import pdfplumber
    parts = []
    has_tables = False
    with pdfplumber.open(file_path) as pdf:
        for i, page in enumerate(pdf.pages, 1):
            text = page.extract_text() or ""
            if text.strip():
                parts.append(f"## Page {i}\n\n{text}\n")
            # 表格提取
            tables = page.extract_tables()
            for j, table in enumerate(tables, 1):
                if not table:
                    continue
                has_tables = True
                # 转 Markdown 表格
                header = table[0] if table else []
                rows = table[1:] if len(table) > 1 else []
                if header:
                    md_table = "| " + " | ".join(str(c or "") for c in header) + " |\n"
                    md_table += "| " + " | ".join("---" for _ in header) + " |\n"
                    for row in rows:
                        md_table += "| " + " | ".join(str(c or "") for c in row) + " |\n"
                    parts.append(f"\n### Table {j} (Page {i})\n\n{md_table}\n")
    content = "\n".join(parts) if parts else ""
    # 评分: 有内容 85+, 有表格 90+（修复：跨所有页检查表格）
    score = 85.0 if content else 30.0
    if has_tables:
        score = min(95.0, score + 5.0)
    return content, score


def parse_with_pymupdf(file_path: str) -> Tuple[str, float]:
    """用 PyMuPDF (fitz) 高速解析 PDF"""
    import fitz
    doc = fitz.open(file_path)
    parts = []
    for i, page in enumerate(doc, 1):
        text = page.get_text("text") or ""
        if text.strip():
            parts.append(f"## Page {i}\n\n{text}\n")
    doc.close()
    content = "\n".join(parts) if parts else ""
    score = 82.0 if content else 30.0
    return content, score


def parse_with_paddleocr(file_path: str) -> Tuple[str, float]:
    """用 PaddleOCR 解析扫描件/图片/扫描版 PDF，返回 (markdown, 质量评分)

    PaddleOCR 支持中文 OCR，可处理纯图像、扫描件、扫描版 PDF、发票等。

    实现说明: Paddle 使用 Intel OpenMP(libiomp5)，与 numpy/opencv/torch 的 GNU OpenMP
    同进程会触发 free(): invalid pointer / SIGABRT，且该信号 Python 无法捕获。
    因此这里通过 subprocess 调用独立的 paddleocr_runner.py 完成推理：
    即使 Paddle 崩溃也只杀子进程，本 worker 不受影响，其余引擎照常工作。
    """
    runner = os.path.join(os.path.dirname(__file__), "paddleocr_runner.py")
    if not os.path.exists(runner):
        raise RuntimeError("PaddleOCR 运行脚本缺失(paddleocr_runner.py)，无法使用该引擎。")

    env = os.environ.copy()
    try:
        proc = subprocess.run(
            [sys.executable, runner, file_path],
            capture_output=True,
            text=True,
            timeout=300,  # 5 分钟超时
            env=env,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("PaddleOCR 解析超时(>300s)")

    # runner 把结果 JSON 打印到 stdout 的某一行；其余为库日志噪声。
    # 取最后一行可解析为 JSON 的输出作为结果。
    result_json = None
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            candidate = json.loads(line)
        except json.JSONDecodeError:
            continue
        result_json = candidate  # 不断覆盖，最终保留最后一条合法 JSON

    if proc.returncode != 0 or result_json is None:
        err = (result_json or {}).get("error") if isinstance(result_json, dict) else None
        stderr = (proc.stderr or "")[-500:]
        detail = err or stderr or f"PaddleOCR 子进程退出码 {proc.returncode}"
        raise RuntimeError(f"PaddleOCR 解析失败: {detail}")

    if "error" in result_json:
        raise RuntimeError(f"PaddleOCR 解析失败: {result_json['error']}")

    content = result_json.get("content", "")
    score = float(result_json.get("score", 30.0))
    return content, score


def parse_with_mineru(file_path: str) -> Tuple[str, float]:
    """用 MinerU 解析复杂文档（公式、双栏、图表），返回 (markdown, 质量评分)

    MinerU 支持版面分析、公式识别、表格识别，适合学术论文/工业手册。
    安装: pip install mineru[all]
    模型源: export MINERU_MODEL_SOURCE=modelscope (国内推荐)

    通过 subprocess 调用 mineru CLI，兼容性最好。
    """
    if shutil.which("mineru") is None:
        raise RuntimeError(
            "MinerU 解析引擎未部署：请执行 `pip install mineru[all]` 并重启服务。"
            "首次运行会自动从 ModelScope 下载版面/公式/表格模型（需联网，建议设置 MINERU_MODEL_SOURCE=modelscope）。"
        )
    output_dir = tempfile.mkdtemp(prefix="mineru_out_")
    md_content = ""
    score = 30.0

    try:
        # 使用 pipeline 后端（纯 CPU 也可运行），优先 modelscope 模型源
        env = os.environ.copy()
        env.setdefault("MINERU_MODEL_SOURCE", "modelscope")

        cmd = ["mineru", "-p", file_path, "-o", output_dir, "-b", "pipeline"]
        logger.info(f"[MinerU] 启动解析: {' '.join(cmd)}")

        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,  # 5分钟超时
            env=env,
        )

        if proc.returncode != 0:
            stderr = proc.stderr or ""
            logger.error(f"[MinerU] 解析失败 (exit {proc.returncode}): {stderr[:500]}")
            raise Exception(f"MinerU 解析失败: {stderr[:200]}")

        # 查找输出目录中的 markdown 文件
        md_files = []
        for root, dirs, files in os.walk(output_dir):
            for f in files:
                if f.endswith('.md'):
                    md_files.append(os.path.join(root, f))

        if md_files:
            # 取第一个（通常只有一个）
            with open(md_files[0], 'r', encoding='utf-8', errors='ignore') as f:
                md_content = f.read()
            score = 92.0 if md_content.strip() else 30.0
            logger.info(f"[MinerU] 解析成功，输出 {len(md_content)} 字符")
        else:
            logger.warning("[MinerU] 未找到输出 markdown 文件")
            raise Exception("MinerU 解析完成但未生成 markdown 文件")

    finally:
        # 清理临时输出目录
        try:
            shutil.rmtree(output_dir, ignore_errors=True)
        except Exception:
            pass

    return md_content, score


def parse_with_docx(file_path: str) -> Tuple[str, float]:
    """用 python-docx 解析 Word 文档"""
    from docx import Document
    doc = Document(file_path)
    parts = []
    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        style = para.style.name.lower() if para.style else ""
        if "heading 1" in style:
            parts.append(f"# {text}\n")
        elif "heading 2" in style:
            parts.append(f"## {text}\n")
        elif "heading 3" in style:
            parts.append(f"### {text}\n")
        else:
            parts.append(f"{text}\n")
    # 表格
    for i, table in enumerate(doc.tables, 1):
        if not table.rows:
            continue
        header = [cell.text.strip() for cell in table.rows[0].cells]
        md_table = "| " + " | ".join(header) + " |\n"
        md_table += "| " + " | ".join("---" for _ in header) + " |\n"
        for row in table.rows[1:]:
            cells = [cell.text.strip() for cell in row.cells]
            md_table += "| " + " | ".join(cells) + " |\n"
        parts.append(f"\n### Table {i}\n\n{md_table}\n")
    content = "\n".join(parts) if parts else ""
    score = 88.0 if content else 30.0
    return content, score


def parse_csv(file_path: str) -> Tuple[str, float]:
    """解析 CSV 文件，转为 Markdown 表格"""
    import csv
    parts = []
    with open(file_path, "r", encoding="utf-8-sig", errors="ignore", newline="") as f:
        reader = csv.reader(f)
        rows = list(reader)
    if not rows:
        return "", 30.0
    header = rows[0]
    md_table = "| " + " | ".join(str(c or "") for c in header) + " |\n"
    md_table += "| " + " | ".join("---" for _ in header) + " |\n"
    for row in rows[1:]:
        # 补齐列数
        while len(row) < len(header):
            row.append("")
        md_table += "| " + " | ".join(str(c or "") for c in row) + " |\n"
    parts.append(f"## CSV Data\n\n{md_table}\n")
    content = "\n".join(parts)
    score = 88.0 if content.strip() else 30.0
    return content, score


def parse_xls(file_path: str) -> Tuple[str, float]:
    """解析 Excel (xls/xlsx) 文件，转为 Markdown 表格"""
    try:
        import openpyxl
    except ImportError:
        raise Exception("服务器未安装 openpyxl，无法解析 Excel 文件")

    wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
    parts = []
    for ws in wb.worksheets:
        sheet_name = ws.title or "Sheet"
        parts.append(f"## {sheet_name}\n")
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            continue
        header = rows[0]
        md_table = "| " + " | ".join(str(c or "") if c is not None else "" for c in header) + " |\n"
        md_table += "| " + " | ".join("---" for _ in header) + " |\n"
        for row in rows[1:]:
            # 补齐列数
            row_list = list(row)
            while len(row_list) < len(header):
                row_list.append(None)
            md_table += "| " + " | ".join(str(c or "") if c is not None else "" for c in row_list) + " |\n"
        parts.append(f"\n{md_table}\n")
    wb.close()
    content = "\n".join(parts)
    score = 90.0 if content.strip() else 30.0
    return content, score


def parse_plain_text(file_path: str) -> Tuple[str, float]:
    """纯文本/HTML/Markdown 直接读取"""
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
    score = 90.0 if content.strip() else 30.0
    return content, score


def parse_document(file_path: str, engine: str) -> Tuple[str, float]:
    """统一入口: 根据引擎名或文件扩展名分发解析器

    Args:
        file_path: 文件路径
        engine: 解析引擎名 (pdfplumber/PyMuPDF/python-docx/PaddleOCR/MinerU/txt/csv/excel)

    Returns:
        (markdown_content, quality_score 0-100)
    """
    ext = os.path.splitext(file_path)[1].lower()

    # 引擎映射
    if engine == "pdfplumber":
        return parse_with_pdfplumber(file_path)
    elif engine == "PyMuPDF":
        return parse_with_pymupdf(file_path)
    elif engine == "python-docx":
        return parse_with_docx(file_path)
    elif engine == "PaddleOCR":
        return parse_with_paddleocr(file_path)
    elif engine == "MinerU":
        return parse_with_mineru(file_path)
    elif engine == "csv":
        return parse_csv(file_path)
    elif engine in ("excel", "openpyxl"):
        return parse_xls(file_path)
    else:
        # 默认: 根据扩展名自动选择
        if ext == ".csv":
            return parse_csv(file_path)
        elif ext in (".xlsx", ".xls"):
            return parse_xls(file_path)
        elif ext in (".docx",):
            return parse_with_docx(file_path)
        elif ext == ".pdf":
            try:
                return parse_with_pdfplumber(file_path)
            except Exception:
                return parse_with_pymupdf(file_path)
        else:
            return parse_plain_text(file_path)
