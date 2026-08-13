# Logo Generated

Logo素材生成 Web 应用。生产运行形态是 React/Vite 前端构建产物，由
FastAPI 后端在同一域名提供页面和 `/api` 接口；后端当前使用 SQLite 和本地
持久化素材目录。

这是生产源码仓库，不包含客户历史、生成图片、测试数据、日志、本地密钥或
开发环境。完整的部署说明见
[`PRODUCTION_DEPLOYMENT.md`](./PRODUCTION_DEPLOYMENT.md)。

## 目录

- `frontend/`：React + TypeScript + Vite 前端。
- `backend/src/`：FastAPI API、业务服务、认证、模型调用和 Lark 通知。
- `backend/src/db/migrations/`：启动时自动执行的 SQLite 数据库迁移。
- `backend/config/app.production.toml`：未挂载配置目录时使用的生产回退配置。
- `backend/config/app.local.production.example.toml`：完整生产配置模板，部署时复制为服务器私有的 `app.toml`。
- `pycore/`：项目内使用的 Python 核心框架。
- `requirements.txt`：已导出的、锁定版本的 Python 生产运行依赖。
- `deploy/`：Windows 环境的初始化、启动、状态和停止脚本。
- `docker-compose.yml`：Docker Compose 生产编排，独立启动前端、后端和 Nginx。
- `docker/`：前后端镜像及 Nginx 配置。

## 首次部署必须准备

1. Python 3.11+ 和 Node.js 20+。
2. 将 `backend/config/app.local.production.example.toml` 复制为服务器私有的
   `backend/config/app.toml`，并通过服务器 Secret 管理器填写：
   管理员账号密码、会话密钥、客户访问令牌加密密钥、模型连接加密密钥、
   Lark 配置加密密钥和正式 HTTPS 域名。`app.toml` 禁止提交到 Git。
3. 创建可写且持久化的目录：
   `backend/data/` 和 `backend/data/assets/`。
4. 使用全新的空数据库启动。程序会自动执行数据库迁移并创建首个管理员。

不要复制开发机上的 `logo_generated.db`、其他 `.db` 文件或历史 `assets/`。
数据库和素材目录属于运行数据，应在服务器侧单独备份；如果将来迁移已批准
的历史数据，数据库、素材和对应加密密钥必须作为一组加密备份迁移。

## Windows 部署

在项目根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\bootstrap.ps1
powershell -ExecutionPolicy Bypass -File .\deploy\start-local.ps1
```

`start-local.ps1` 会运行真实模式前端构建（`VITE_USE_MOCK=false`），然后在
`127.0.0.1:8099` 启动 FastAPI，并由同一进程提供前端页面和 API。检查和停止：

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\status.ps1
powershell -ExecutionPolicy Bypass -File .\deploy\stop.ps1
```

临时公网验收可在本机服务启动后运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\start-quick-tunnel.ps1
```

Quick Tunnel 地址会变化，只适合验收。正式客户访问应使用固定域名的
Cloudflare Named Tunnel 或 HTTPS 反向代理，并同步更新两个前端 Base URL。

## Docker Compose 部署（Linux / 云服务器）

推荐使用仓库内的 Docker Compose 部署：

```bash
cp backend/config/app.local.production.example.toml backend/config/app.toml
# 编辑服务器私有的 app.toml，填入管理员、域名和后台配置；不要提交该文件
python3 deploy/generate-production-secrets.py
# 校验配置不会打印密钥；通过后再启动
python3 deploy/validate-production-config.py backend/config/app.toml
mkdir -p docker-data/backend
docker compose up -d --build
docker compose ps
```

默认端口映射为：前端容器内置 Nginx `8098:80`、后端 `8099:8099`。可在启动前用环境变量改宿主端口，例如
`FRONTEND_PORT=8098 BACKEND_PORT=8099 docker compose up -d --build`。
正式用户访问前端容器的 Nginx 端口 `8098`；后端 `8099` 仅用于运维检查，建议限制公网访问安全组。

持久化目录是 `docker-data/backend/`（容器内 `/app/backend/data`），其中包含
`logo_generated.db` 和 `assets/`。这些目录已被 Git 忽略，必须纳入服务器备份。
首次部署使用空目录，不要复制开发机历史数据库或素材。

前端容器使用 `docker/frontend.conf` 作为唯一 Nginx 配置，代理 `/api`、`/ws` 和 `/health`，并将其他路径提供给前端 SPA。当前生产构建默认使用 `/generate-logo/` 子路径；宿主机 Nginx 应使用 `location ^~ /generate-logo/` 将请求转发到 `http://127.0.0.1:8098/`，保留 `proxy_pass` 末尾 `/` 以剥离该前缀。
如需 HTTPS，应在该容器前增加云负载均衡、Cloudflare Tunnel 或宿主机 TLS 反向代理，不要再在 Compose 内启动第二个 Nginx。

Compose 按当前生产方式只读挂载整个 `backend/config/` 目录；该宿主机目录中必须
存在完整的 `app.toml`。不要直接挂载空目录，否则容器无法读取配置。

若部署环境不能使用 Docker，才需要自行补充 systemd 或其他进程管理器：

1. `npm ci && npm run build:real`。
2. 创建 Python 虚拟环境，并执行 `python -m pip install -r requirements.txt` 安装依赖。
3. 使用 Uvicorn 启动 `src.production:create_app`。
4. 用 systemd、容器编排或其他进程管理器常驻运行。
5. 在 Uvicorn 前配置 HTTPS 反向代理或 Cloudflare Named Tunnel。
6. 将 `backend/data/` 配置为持久化存储并建立备份策略。

## 生产构建

前端真实模式构建：

```bash
cd frontend
npm ci
npm run build:real
```

Docker 后端入口优先读取挂载目录中的 `backend/config/app.toml`。生产环境必须保持：

- `app_env = "production"`
- `debug = false`
- `enable_development_seeds = false`
- `enable_real_model_smoke_tests = true`（管理后台连通性测试需要；每次测试可能消耗供应商额度）
- `VITE_USE_MOCK=false`

## 不应进入仓库的内容

`.gitignore` 已排除以下内容：

- `backend/data/*.db`、`backend/data/assets/` 和受控诊断数据；
- `backend/config/app.toml`、`backend/config/app.local.toml`、`.env` 及其他本地 Secret；
- `backend/tests/`、`frontend/tests/` 和测试专用脚本；
- `.sdd/`、日志、虚拟环境、`node_modules/` 和 `dist/`；
- 开发文档和本地配置草稿。

提交前请确认没有把 API Key、管理员密码、Webhook、客户信息或历史图片加入
Git。生产私有配置只通过服务器 Secret 管理或主机私有文件提供。
