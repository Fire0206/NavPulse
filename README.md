# NavPulse — 基金实时估值系统

<p align="center">
  <strong>基于重仓股实时行情的基金净值估算 · 多用户 Web 应用</strong>
</p>

## ✨ 功能亮点

| 功能 | 说明 |
|------|------|
| **实时估值** | 通过基金季度披露的重仓持仓 × 股票实时行情，估算当日基金涨跌幅 |
| **持仓组合** | 多只基金持仓管理，当日盈亏、总市值一目了然 |
| **自选关注** | 不实际持仓，仅关注基金实时涨跌 |
| **行情总览** | 大盘指数 · 全市场涨跌分布 · 行业板块实时涨跌 |
| **分时走势** | 日内估值分时曲线，直观展示基金当日波动 |
| **历史净值** | 任意时间段净值走势图 + 交易记录标记 |
| **联接基金穿透** | 自动识别联接基金，穿透到底层 ETF 真实持仓计算估值 |
| **多端适配** | 手机优先设计，同时兼容平板与 PC 浏览器 |
| **多主题色** | 樱花粉 / 天空蓝 / 星空紫 / 薄荷绿 / light（纯白风） / dark（高级灰暗色） |
| **隐私模式** | 一键模糊持仓金额 |

## 🛠 技术栈

| 层级 | 技术 |
|------|------|
| 后端框架 | **FastAPI** (异步) + **Uvicorn** |
| 前端 | **Vue 3** (ESM CDN) + **ECharts 5.5** + **Bootstrap 5.3** |
| ORM / 数据库 | **SQLAlchemy** + **SQLite** (WAL 模式) |
| 认证 | **JWT** (`python-jose`) + **bcrypt** |
| 行情数据 | **akshare** (基金持仓/名称/历史) + **腾讯行情 API** (股票分钟线) |
| 调度器 | **APScheduler** (AsyncIOScheduler) |
| 部署 | **Gunicorn** + Uvicorn Worker + Nginx 反向代理 |

## 📦 快速开始

### 1. 克隆项目

```bash
git clone https://github.com/Fire0206/NavPulse.git
cd NavPulse
```

### 2. 安装依赖

```bash
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

pip install -r requirements.txt
```

### 3. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，必须设置 JWT_SECRET_KEY
```

> 生成密钥：`python -c "import secrets; print(secrets.token_urlsafe(32))"`

### 4. 启动

```bash
# 开发模式
DEBUG=true python -m app.main

# 或使用 uvicorn
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

浏览器访问：**http://localhost:8000**

### 5. 生产部署

```bash
gunicorn -c gunicorn_conf.py app.main:app
```

详细部署指南请参见 [DEPLOY.md](DEPLOY.md)。

## 🔒 安全特性

> **适配开源项目与生产环境部署**

| 安全措施 | 说明 |
|---------|------|
| **强密码策略** | 8位+大小写字母+数字，bcrypt 哈希存储 |
| **登录速率限制** | 5分钟内最多5次失败尝试（基于 IP+用户名） |
| **安全响应头** | HSTS、CSP、X-Frame-Options、X-Content-Type-Options 等 |
| **JWT 密钥保护** | 生产环境强制检查 `JWT_SECRET_KEY` 配置 |
| **模糊化错误** | 防止用户名枚举攻击 |

**生产部署必做**：
1. 设置固定 `JWT_SECRET_KEY`（否则无法启动）
2. 配置 `ENVIRONMENT=production`
3. 限制 `CORS_ORIGINS` 为真实域名
4. 启用 HTTPS（HSTS 自动生效）

详见 [SECURITY.md](SECURITY.md)

## ⚙️ 环境变量

| 变量 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `JWT_SECRET_KEY` | ✅ | 随机生成 | JWT 签名密钥（**生产必须固定**） |
| `ENVIRONMENT` | | `development` | `production` 时启用生产安全策略 |
| `TOKEN_EXPIRE_MINUTES` | | `1440` | Token 有效期（分钟） |
| `CORS_ORIGINS` | | `*` | 允许的前端域名，逗号分隔 |
| `DEBUG` | | `false` | 启用 Swagger 文档 + JS 无缓存 |
| `DATABASE_URL` | | `sqlite:///app/data/navpulse.db` | 数据库连接字符串 |
| `ICP_RECORD` | | *(空)* | ICP 备案号，留空不显示 |
| `PORT` | | `8000` | 监听端口 |

**生产环境 .env 示例**：
```bash
ENVIRONMENT=production
JWT_SECRET_KEY=<使用 python -c "import secrets; print(secrets.token_urlsafe(32))" 生成>
CORS_ORIGINS=https://yourdomain.com
TOKEN_EXPIRE_MINUTES=1440
```

## 📁 项目结构

```
NavPulse/
├── app/
│   ├── main.py              # FastAPI 入口 + 生命周期管理
│   ├── database.py          # SQLAlchemy 引擎 + SQLite WAL
│   ├── scheduler.py         # APScheduler 定时任务
│   ├── state.py             # 全局内存缓存 + SQLite 持久化
│   ├── models/              # ORM 模型
│   ├── routers/             # API 路由（认证/持仓/自选/行情/基金/系统）
│   ├── services/            # 业务逻辑层
│   │   ├── valuation_service.py  # 核心估值引擎
│   │   ├── fund_service.py       # 基金持仓 + 净值
│   │   ├── market_service.py     # 大盘 + 涨跌分布 + 板块
│   │   ├── portfolio_service.py  # 持仓组合
│   │   ├── auth_service.py       # JWT 认证
│   │   ├── trading_calendar.py   # 交易日历
│   │   └── transaction_service.py # 交易记录
│   ├── static/              # 前端静态资源 (CSS/JS/Vue组件)
│   └── templates/           # Jinja2 HTML 模板
├── gunicorn_conf.py         # Gunicorn 生产配置
├── start.sh                 # 宝塔面板启动脚本
├── requirements.txt         # Python 依赖
├── .env.example             # 环境变量示例
├── DEPLOY.md                # 部署文档
└── LICENSE                  # MIT 许可证
```

## 📱 移动端适配

- 底部导航栏固定布局（持有 / 自选 / 行情 / 设置）
- 下拉刷新 + 手动刷新按钮
- 响应式卡片布局，`max-width: 760px` 居中
- 禁用缩放，原生 App 般的操作体验

## ⚠️ 免责声明

- 本项目仅供学习交流使用，不构成投资建议
- 估值数据基于基金季度公开持仓 × 股票实时行情加权计算，仅供参考
- 实际净值以基金公司当日公布为准

## 📄 License

[MIT License](LICENSE)
