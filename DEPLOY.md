# KG Platform 服务器部署指南

## 方案概述

通过 **Git 推送代码 → 服务器拉取 → Docker Compose 一键构建部署**。

```
本地电脑 --git push--> Git仓库 --git pull--> 服务器 --docker compose up--> 运行
```

---

## 一、服务器环境准备

在你的服务器上安装 Docker 和 Docker Compose：

```bash
# 1. 安装 Docker
curl -fsSL https://get.docker.com | sh

# 2. 启动 Docker 服务
sudo systemctl start docker
sudo systemctl enable docker

# 3. 验证安装
docker --version
docker compose version
```

> 如果服务器在国内，Docker 安装后建议配置镜像加速器：
> ```bash
> sudo mkdir -p /etc/docker
> sudo tee /etc/docker/daemon.json <<-'EOF'
> {
>   "registry-mirrors": ["https://docker.mirrors.ustc.edu.cn"]
> }
> EOF
> sudo systemctl restart docker
> ```

---

## 二、代码推送到 Git 仓库

### 方案 A：使用 GitHub / Gitee（推荐）

```bash
# 1. 在本地项目目录初始化 Git
cd kg-platform
git init

# 2. 添加远程仓库（替换为你的仓库地址）
git remote add origin https://github.com/你的用户名/kg-platform.git
# 或使用 Gitee（国内更快）:
# git remote add origin https://gitee.com/你的用户名/kg-platform.git

# 3. 提交代码
git add .
git commit -m "KG Platform 初始提交"

# 4. 推送到远程仓库
git branch -M main
git push -u origin main
```

### 方案 B：如果仓库太大（含模型文件）

`download/` 目录包含大量模型文件，**不应提交到 Git**（已在 `.gitignore` 中排除）。
模型文件应在服务器上单独下载。

```bash
# 确认 .gitignore 已排除 download/ 目录
cat .gitignore | grep download
# 应输出: download/

# 如果不小心 add 了 download/，先取消跟踪
git rm -r --cached download/
git commit -m "移除模型文件跟踪"
```

---

## 三、服务器部署

### 1. 拉取代码

```bash
# 在服务器上选择部署目录
cd /opt
git clone https://github.com/你的用户名/kg-platform.git
cd kg-platform
```

### 2. 配置环境变量

```bash
# 复制环境变量模板
cp .env.example .env

# 编辑 .env 文件，填入真实密码和密钥
vi .env
```

`.env` 文件内容示例（请替换为真实值）：

```ini
POSTGRES_USER=postgres
POSTGRES_PASSWORD=MyStr0ngDBPass2026!
POSTGRES_DB=kg_platform

NEO4J_PASSWORD=MyStr0ngNeo4jPass!

# 用以下命令生成随机密钥:
# python3 -c "import secrets; print(secrets.token_urlsafe(32))"
JWT_SECRET=xK9m2vQ7nR4pL8wF3hJ6tY1bN5cE0aZ
ENCRYPTION_KEY=jH7gD4sA9pV2xM6kR1cF3nB8wQ5tL0y

CORS_ORIGINS=*
```

### 3. 构建并启动

```bash
# 构建镜像并启动所有服务（首次需要几分钟）
docker compose up -d --build

# 查看启动状态
docker compose ps

# 查看后端日志
docker compose logs -f backend-api
```

### 4. 创建管理员账号

```bash
# 进入后端容器创建管理员
docker compose exec backend-api python -c "
from app.database import SessionLocal
from app.models import User
from app.utils.security import hash_password

db = SessionLocal()
if not db.query(User).filter(User.username == 'admin').first():
    db.add(User(username='admin', password_hash=hash_password('admin123'), role='admin'))
    db.commit()
    print('管理员创建成功: admin / admin123')
else:
    print('管理员已存在')
db.close()
"
```

### 5. 验证部署

```bash
# 前端访问
curl http://服务器IP/

# 后端健康检查
curl http://服务器IP:8000/health

# 后端 Swagger 文档
# 浏览器打开: http://服务器IP:8000/docs
```

---

## 四、日常运维命令

```bash
# 查看服务状态
docker compose ps

# 查看日志
docker compose logs -f backend-api    # 后端日志
docker compose logs -f frontend-app   # 前端日志
docker compose logs -f postgres-db    # 数据库日志

# 重启服务
docker compose restart backend-api

# 停止所有服务
docker compose down

# 停止并删除数据卷（⚠️ 会丢失所有数据）
docker compose down -v

# 更新代码后重新部署
git pull
docker compose up -d --build

# 启动 Neo4j（按需）
docker compose --profile full up -d
```

---

## 五、更新部署（后续代码更新）

当你在本地修改代码后，更新服务器：

```bash
# ---- 本地电脑 ----
git add .
git commit -m "修复xxx问题"
git push

# ---- 服务器 ----
cd /opt/kg-platform
git pull
docker compose up -d --build
```

---

## 六、数据备份与恢复

### 备份

```bash
# 备份 PostgreSQL 数据库
docker compose exec postgres-db pg_dump -U postgres kg_platform > backup_$(date +%Y%m%d).sql

# 备份上传的文件
docker run --rm -v kg-platform_uploads-data:/data -v $(pwd):/backup alpine \
    tar czf /backup/uploads_backup_$(date +%Y%m%d).tar.gz /data
```

### 恢复

```bash
# 恢复数据库
cat backup_20260709.sql | docker compose exec -T postgres-db psql -U postgres kg_platform

# 恢复上传文件
docker run --rm -v kg-platform_uploads-data:/data -v $(pwd):/backup alpine \
    tar xzf /backup/uploads_backup_20260709.tar.gz -C /
```

---

## 七、安装可选的 AI 抽取引擎

基础镜像只包含 LLM Prompt 抽取和基础解析器。如需 GLiNER / UIE / PaddleOCR / MinerU 等引擎：

```bash
# 进入后端容器安装
docker compose exec backend-api pip install gliner spacy
docker compose exec backend-api python -m spacy download en_core_web_sm

# 或修改 backend/requirements.txt 取消注释对应依赖后重新构建
# 然后: docker compose up -d --build backend-api
```

> 注意：PaddlePaddle 和 MinerU 体积较大（数 GB），建议在有 GPU 的服务器上安装。
> 安装后需重启容器: `docker compose restart backend-api`

---

## 八、常见问题

### Q: 端口被占用怎么办？
修改 `docker-compose.yml` 中的端口映射，例如将 `80:80` 改为 `8080:80`。

### Q: 如何配置 HTTPS？
在 nginx.conf 中添加 SSL 证书配置，或在前端容器前加一个 Caddy/Traefik 反向代理。

### Q: 数据库密码忘了怎么办？
```bash
# 修改 .env 中的 POSTGRES_PASSWORD
# 然后重建数据库容器（会丢失数据！）
docker compose down postgres-db
docker volume rm kg-platform_postgres-data
docker compose up -d --build
```

### Q: 服务器内存不够怎么办？
- 不启动 Neo4j（默认不启动）
- 后端添加 `--workers 1` 限制工作进程
- 在 docker-compose.yml 中添加内存限制:
```yaml
backend-api:
  deploy:
    resources:
      limits:
        memory: 2G
```

### Q: 如何查看数据库内容？
```bash
# 进入 PostgreSQL 容器
docker compose exec postgres-db psql -U postgres kg_platform

# 查看表
\dt

# 查询三元组
SELECT * FROM triples_raw LIMIT 10;

# 退出
\q
```
