# ============================================================
# KG Platform Backend Dockerfile
# ============================================================
FROM python:3.11-slim

WORKDIR /app

# 系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc curl \
    && rm -rf /var/lib/apt/lists/*

# Python 依赖（单独一层，利用 Docker 缓存）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 应用代码
COPY . .

# 创建上传目录 + 设置脚本权限
RUN mkdir -p /app/uploads && chmod +x /app/entrypoint.sh

# 健康检查
HEALTHCHECK --interval=10s --timeout=5s --retries=3 --start-period=30s \
    CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000

# 启动脚本：等待DB → 建表 → 启动服务
CMD ["/app/entrypoint.sh"]
