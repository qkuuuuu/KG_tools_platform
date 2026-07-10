# ============================================================
# KG Platform Frontend Dockerfile
# ============================================================
# 构建: docker build -t kg-frontend .
# 策略:
#   阶段1 (build): npm build 产出 dist/
#   阶段2 (serve): nginx 托管静态文件 + API 反向代理
# ============================================================
FROM node:20-alpine AS build

WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
