"""HTTP 响应工具"""
from urllib.parse import quote


def attachment_filename(filename: str) -> str:
    """构造 Content-Disposition 头，兼容中文等非 ASCII 文件名（RFC 5987）

    同时提供 ASCII 回退名与 UTF-8 编码的 filename*，避免 Starlette 因
    非 ASCII 头值抛出 UnicodeEncodeError -> 500。文件名中的引号/换行
    会被 quote() 正确转义，杜绝响应头注入。
    """
    ascii_name = filename.encode("ascii", "ignore").decode() or "download"
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"
