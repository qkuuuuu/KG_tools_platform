"""文档解析引擎 - 真实实现
支持: pdfplumber / PyMuPDF / python-docx / PaddleOCR / MinerU / 纯文本 / CSV / Excel
"""
import os
import re
import time
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
    安装: pip install paddlepaddle paddleocr
    """
    try:
        from paddleocr import PaddleOCR
    except ImportError:
        raise RuntimeError(
            "PaddleOCR 解析引擎未部署：请执行 `pip install paddlepaddle paddleocr` 并重启服务。"
            "首次运行会自动下载中文 OCR 模型（需联网）。"
        )
    import fitz  # PyMuPDF 用于将 PDF 页面转为图片

    # 初始化 PaddleOCR（中文 + 角度分类）
    ocr = PaddleOCR(use_angle_cls=True, lang='ch', show_log=False)

    parts = []
    ext = os.path.splitext(file_path)[1].lower()

    if ext == '.pdf':
        # PDF: 逐页转图片后 OCR
        doc = fitz.open(file_path)
        for i, page in enumerate(doc, 1):
            # 渲染页面为图片 (DPI=200 平衡清晰度与速度)
            pix = page.get_pixmap(dpi=200)
            img_path = file_path + f"_page_{i}.png"
            pix.save(img_path)
            try:
                result = ocr.ocr(img_path, cls=True)
                page_text = _format_ocr_result(result)
                if page_text.strip():
                    parts.append(f"## Page {i}\n\n{page_text}\n")
            finally:
                # 清理临时图片
                if os.path.exists(img_path):
                    os.remove(img_path)
        doc.close()
    else:
        # 图片直接 OCR
        result = ocr.ocr(file_path, cls=True)
        page_text = _format_ocr_result(result)
        if page_text.strip():
            parts.append(page_text)

    content = "\n".join(parts) if parts else ""
    score = 80.0 if content else 30.0
    return content, score


def _format_ocr_result(result) -> str:
    """将 PaddleOCR 结果格式化为纯文本

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
