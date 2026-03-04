# Gunicorn 配置文件 (宝塔面板 Python 项目使用)
# 启动命令: gunicorn -c gunicorn_conf.py app.main:app

import multiprocessing

# 绑定地址与端口（宝塔 Nginx 反代到此端口）
bind = "127.0.0.1:8000"

# Worker 配置
# UvicornWorker 支持 async/await，是 FastAPI 的推荐 worker
worker_class = "uvicorn.workers.UvicornWorker"
workers = min(multiprocessing.cpu_count(), 4)  # 最多 4 个 worker

# 超时设置（akshare 爬虫可能较慢，给足时间）
timeout = 120
graceful_timeout = 30
keepalive = 5

# 日志
accesslog = "-"       # stdout，宝塔会自动捕获
errorlog = "-"        # stdout
loglevel = "info"

# 可取消注释以写入日志文件（宝塔面板已自动捕获 stdout，一般不需要）
# accesslog = "/www/wwwroot/NavPulse/logs/access.log"
# errorlog = "/www/wwwroot/NavPulse/logs/error.log"

# 进程管理
daemon = False        # 宝塔自己管理守护进程，这里不要设 True
preload_app = False   # False 避免 APScheduler 在 fork 前启动导致问题
max_requests = 1000   # 每个 worker 处理 1000 个请求后自动重启（防内存泄漏）
max_requests_jitter = 50
