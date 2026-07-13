# ============================================================
# KG Platform Backend Dockerfile
# ============================================================
FROM python:3.11-slim

# ============================================================
# 模型缓存统一根目录
# 构建期 predownload_models.py 把大模型下载到这里并随镜像打包；
# 运行时服务进程继承同一套环境变量，直接命中已下载模型，不再联网。
# 注意: 该目录不能挂命名卷（否则会遮住镜像内已下载的模型）。
# ============================================================
ENV MODEL_ROOT=/opt/models
ENV HOME=/opt/models
ENV HF_HOME=/opt/models/.cache/huggingface
ENV HF_ENDPOINT=https://hf-mirror.com
ENV MODELSCOPE_CACHE=/opt/models/.cache/modelscope
ENV PADDLENLP_HOME=/opt/models/.paddlenlp
ENV MINERU_MODEL_SOURCE=modelscope
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# 系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc curl \
    && rm -rf /var/lib/apt/lists/*

# Python 依赖（单独一层，利用 Docker 缓存）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 构建期预下载所有大模型（缓存写入 /opt/models，随镜像打包）
COPY predownload_models.py .
RUN mkdir -p /opt/models && python predownload_models.py

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
