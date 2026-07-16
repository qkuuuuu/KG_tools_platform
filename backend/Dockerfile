# ============================================================
# KG Platform Backend Dockerfile
# ============================================================
FROM python:3.10.9-slim

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
# libgl1 / libglib2.0-0: 修复 cv2(PaddleOCR / MinerU) 运行期报
#   ImportError: libGL.so.1: cannot open shared object file（slim 镜像缺系统 GL 库）
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev build-essential gfortran curl \
    libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# 关闭可能存在的"强制哈希校验"(部分加固版基础镜像在 /etc/pip.conf 开启了
# require-hashes=true)。本项目的 requirements.txt 采用版本约束而非哈希锁版，
# 若开启哈希校验，连 wrapt 这类传递依赖都会因无 --hash 而安装失败。
# ENV 优先级高于 pip.conf，可覆盖镜像内配置。
ENV PIP_REQUIRE_HASHES=false
# 超时/重试必须在「pip install -r requirements.txt」之前设置！否则装 torch/paddle 等
# 大依赖时会用 pip 默认 15s 超时，慢网下极易 Read timed out（历史构建曾因此失败）。
# 上移后这层（含 758MB paddle / cu124 torch）也有了 120s 超时 + 10 次重试兜底。
ENV PIP_DEFAULT_TIMEOUT=120
ENV PIP_RETRIES=10

# Python 依赖（单独一层，利用 Docker 缓存）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 修复 OpenMP 运行时冲突导致的 free(): invalid pointer / SIGABRT 崩溃:
# Paddle 的 wheel 自带 libgomp.so.1(OpenMP 运行时)，与系统/numpy/opencv/torch 加载的
# libgomp 重复驻留同一进程，退出 finalize 时互相 free 对方内存 → glibc Abort。
# 处理要点（踩过坑，务必照此）:
#   - 装系统 libgomp1，并【只删 Paddle 自带的那一份】(site-packages/paddle 下的
#     libgomp.so*)，强制 Paddle 改用系统 libgomp，消除重复 OpenMP。
#   - 【绝不能删 torch 自带的 libgomp-a34b3233.so.1】！torch 的 wheel 把 libgomp
#     改名内置在 site-packages/torch/lib/ 下，删掉后 import torch 直接
#     OSError: libgomp-a34b3233.so.1 挂掉，连后端都起不来。用 `libgomp.so*` 精确匹配
#     可避开 torch 这份(它前缀带哈希，不匹配)。
#   - KMP_DUPLICATE_LIB_OK=TRUE 允许 Intel OpenMP(libiomp5) 重复初始化，避免 abort；
#     OMP_NUM_THREADS=1 降低 OpenMP 资源竞争。
# 放在 pip 层之后，不影响已缓存的 pip 层(重建不必重拉 torch/paddle)。
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && find /usr/local/lib/python3.10/site-packages/paddle* -name 'libgomp.so*' -delete \
    && rm -rf /var/lib/apt/lists/*
ENV KMP_DUPLICATE_LIB_OK=TRUE
ENV OMP_NUM_THREADS=1

# pip 下载健壮性：
# 重要：绝对【不要】设置 PIP_INDEX_URL / PIP_EXTRA_INDEX_URL 指向第三方镜像（含清华、pypi.org 额外源）！
# 本构建环境存在拦截代理，对 Tsinghua 镜像和 pypi.org 额外源都会返回伪造的 "999.9.9" 版本号，
# 导致 zh-core-web-sm 解析失败（实测: from versions: 999.9.9）。
# 保持默认 pypi.org 主源——requirements.txt 那步已经用默认源成功装完 torch/paddle，证明默认源可用。
# （超时/重试已上移到 requirements 安装层之前统一设置。）

# spaCy 模型安装（关键排障）：
# 本构建环境的拦截代理对 zh-core-web-sm / en-core-web-sm 一律返回伪造的 "999.9.9"
# 版本号，走任何 pip 索引（默认 pypi.org / 清华 / extra）都会解析失败；而
# `python -m spacy download` 内嵌 pip 在慢速下又频繁 ReadTimeout。
# 故改为：curl 断点续传(-C -) + shell 循环重试(扛住慢速/断流) 先把 wheel 从
# GitHub releases 拉到本地，再用 `pip install --no-index --no-deps` 装本地 wheel：
#   --no-index → 彻底不碰被污染的 pypi；
#   --no-deps  → spacy 及其依赖已在 requirements 层装好，无需再解析。
# 模型版本随"已安装的 spacy 主版本"自动匹配（spacy 3.x → 模型 x.y.0）。
RUN set -eux; \
    SPACY_MM=$(python -c "import spacy; print('.'.join(spacy.__version__.split('.')[:2]))"); \
    echo "installed spacy major.minor = ${SPACY_MM}"; \
    for m in "zh_core_web_sm" "en_core_web_sm"; do \
        whl="${m}-${SPACY_MM}.0-py3-none-any.whl"; \
        url="https://github.com/explosion/spacy-models/releases/download/${m}-${SPACY_MM}.0/${whl}"; \
        for i in $(seq 1 30); do \
            if curl -fL --connect-timeout 60 --speed-limit 1 --speed-time 30 -C - -o "/tmp/${whl}" "${url}"; then break; fi; \
            echo "retry ${i} for ${whl}"; sleep 3; \
        done; \
        ls -l "/tmp/${whl}"; \
    done; \
    pip install --no-cache-dir --no-index --no-deps /tmp/zh_core_web_sm-*.whl /tmp/en_core_web_sm-*.whl; \
    rm -f /tmp/zh_core_web_sm-*.whl /tmp/en_core_web_sm-*.whl

# 离线模型包（可选）：若需离线预置，把模型按 /opt/models 的目录结构放入
# ./models_offline/ 即可，这里整体 COPY 进镜像，预下载脚本会直接命中缓存、不再联网。
# 目录为空（仅 .gitkeep）时无害，predownload 仍走网络兜底（本方案即走网络下载）。
COPY models_offline/ /opt/models/

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
