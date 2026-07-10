#!/bin/bash
set -e

echo "=== KG Platform 后端启动 ==="

# 1. 等待数据库就绪
echo "[1/3] 等待数据库就绪..."
until python -c "
import psycopg2
import os
url = os.environ.get('DATABASE_URL', '')
# 从 DATABASE_URL 解析连接参数
import re
m = re.match(r'postgresql\+\w+://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)', url)
if m:
    psycopg2.connect(host=m.group(3), port=m.group(4), user=m.group(1), password=m.group(2), dbname=m.group(5))
else:
    exit(1)
" 2>/dev/null; do
  echo "  数据库未就绪，5秒后重试..."
  sleep 5
done
echo "  数据库已就绪"

# 2. 初始化数据库表 + 管理员
echo "[2/3] 初始化数据库表..."
python init_db.py || echo "  [警告] init_db.py 执行失败，可能表已存在"

# 3. 启动 FastAPI
echo "[3/3] 启动 FastAPI 服务..."
exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
