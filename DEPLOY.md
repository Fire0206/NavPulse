# ============================================
# NavPulse 宝塔面板部署指南
# ============================================

## 一、环境准备

### 1. 宝塔安装 Python 项目管理器
- 宝塔面板 -> 软件商店 -> 搜索「Python项目管理器」-> 安装

### 2. 创建 Python 项目
- 打开「Python项目管理器」-> 添加项目
- **项目路径**: `/www/wwwroot/NavPulse`
- **Python 版本**: >= 3.10（推荐 3.11）
- **框架**: FastAPI
- **启动方式**: gunicorn
- **启动命令**: `gunicorn -c gunicorn_conf.py app.main:app`
- **端口**: 8000

---

## 二、上传文件

将整个项目文件夹上传到服务器 `/www/wwwroot/NavPulse`，目录结构：

```
/www/wwwroot/NavPulse/
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── database.py
│   ├── scheduler.py
│   ├── state.py
│   ├── data/           # 运行时自动创建，存放 SQLite 数据库
│   ├── models/
│   ├── routers/
│   ├── services/
│   ├── static/
│   └── templates/
├── gunicorn_conf.py
├── requirements.txt
├── start.sh
└── README.md
```

---

## 三、安装依赖

进入项目虚拟环境后执行：

```bash
cd /www/wwwroot/NavPulse
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

> 如果 akshare 安装缓慢，可单独安装：
> `pip install akshare -i https://pypi.tuna.tsinghua.edu.cn/simple`

---

## 四、Nginx 反向代理配置

在宝塔面板中添加一个站点，然后在站点设置 -> 反向代理中添加：

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    # WebSocket 支持（如后续需要）
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";

    # 超时设置（估值计算可能较慢）
    proxy_read_timeout 120s;
    proxy_connect_timeout 10s;
}
```

或者直接使用宝塔的「反向代理」功能：
- 代理名称: NavPulse
- 目标 URL: http://127.0.0.1:8000
- 发送域名: $host

---

## 五、配置环境变量

在项目根目录创建 `.env` 文件（**必须**设置 JWT 密钥）：

```bash
cd /www/wwwroot/NavPulse
cp .env.example .env
```

编辑 `.env`：

```ini
# 必须！用以下命令生成：python -c "import secrets;print(secrets.token_urlsafe(32))"
JWT_SECRET_KEY=你的随机密钥

# 你的域名（CORS 白名单，逗号分隔）
CORS_ORIGINS=https://你的域名.com

# ICP 备案号（留空则页面不显示）
ICP_RECORD=粤ICP备XXXXXXXXX号

# 生产环境不要开 DEBUG
DEBUG=false
```

> 也可以在宝塔 Python 项目管理器的「环境变量」中配置。如果同时存在 `.env` 文件和宝塔面板的环境变量，面板变量优先级更高。

如果遇到编码问题，额外添加：

```
LANG=en_US.UTF-8
LC_ALL=en_US.UTF-8
PYTHONIOENCODING=utf-8
```

---

## 六、启动与管理

### 方式一：通过宝塔 Python 项目管理器
- 点击「启动」即可，宝塔会自动守护进程

### 方式二：手动启动
```bash
cd /www/wwwroot/NavPulse
source venv/bin/activate
gunicorn -c gunicorn_conf.py app.main:app
```

### 方式三：使用 start.sh
```bash
cd /www/wwwroot/NavPulse
chmod +x start.sh
bash start.sh
```

---

## 七、常见问题

### Q: 启动后页面空白
检查 `app/static/` 和 `app/templates/` 目录是否已正确上传。

### Q: 数据库权限错误
```bash
chmod 755 /www/wwwroot/NavPulse/app/data
```

### Q: akshare 报错
确保 Python >= 3.10，并使用最新版:
```bash
pip install --upgrade akshare
```

### Q: 端口被占用
```bash
lsof -i:8000
kill -9 <PID>
```

---

## 八、健康检查

部署成功后访问：
- 首页: `http://你的域名/`
- 健康检查: `http://你的域名/health`
- API 状态: `http://你的域名/api/status`
