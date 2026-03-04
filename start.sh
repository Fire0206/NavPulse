#!/bin/bash
# NavPulse 宝塔部署启动脚本
# 用法: bash start.sh

# 进入项目目录
cd "$(dirname "$0")"

# 激活虚拟环境（宝塔创建的 Python 项目通常在 venv 中）
if [ -d "venv" ]; then
    source venv/bin/activate
elif [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# 确保 data 目录存在
mkdir -p app/data

# 加载 .env（如存在）
if [ -f ".env" ]; then
    set -a
    source .env
    set +a
fi

# 使用 gunicorn + uvicorn worker 启动
exec gunicorn -c gunicorn_conf.py app.main:app
