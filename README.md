# hello-fullstack

Minimal full-stack example:

- **Frontend**: static `index.html` deployed to GitHub Pages
- **Backend**: FastAPI deployed to Render

## Local dev

### Backend

```bash
python -m venv .venv
./.venv/Scripts/pip install -r backend/requirements.txt
./.venv/Scripts/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 --app-dir backend
```

Test:

- `http://localhost:8000/health`
- `http://localhost:8000/api/hello`
- `http://localhost:8000/api/hello?name=Ada` (personalized greeting)
- `http://localhost:8000/sheng/` (**升级** 拖拉機试玩静态页 — 与同进程 API 同源，无需配 CORS)

### Frontend

Open `frontend/index.html` in a browser. Type a name to see live API responses (debounced), or use **Greet**.

By default it calls `http://localhost:8000`. After deploying the backend, set `API_BASE` in `frontend/index.html` to your Render URL.

## Deploy

### Backend (Render)

Create a new **Web Service** from this repo.

- **Root directory**: `backend`
- **Build command**: `pip install -r requirements.txt`
- **Start command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`

After deploy, you’ll have a backend URL like `https://your-service.onrender.com`.

### Frontend (GitHub Pages)

This repo includes a GitHub Actions workflow that publishes the `frontend/` folder to GitHub Pages.

1. Push this repo to GitHub.
2. In GitHub: **Settings → Pages**
   - **Build and deployment**: GitHub Actions
3. Update `API_BASE` in `frontend/index.html` to your Render URL and push again.

### 升级拖拉机试玩 `/sheng/`

在项目 Pages 就绪后浏览器打开 **`https://<你的 GitHub 用户名>.github.io/<仓库名>/sheng/`**（与仓库同名路径；用户页站点则用 `用户名.github.io` 根路径下的子路径）。

试玩脚本会默认访问公共后端 **`https://hello-fullstack-py.onrender.com`**。单手试玩时可勾选「轮到其他座位时代出首张合法牌」；默认关闭，不会自动替其他家出牌。若打不开或你从 fork 自部署后端，须在 Render **环境变量** 中设置 **`CORS_ALLOW_ORIGINS`**（允许多个，逗号分隔），包含你的前端源站，通常为 **`https://<用户名>.github.io`**。

## Windows quick start (using the Projects .venv)

If you already have a virtual environment at `C:\Users\stqcn\Projects\.venv`, you can run the backend without creating a new one:

```powershell
.\scripts\dev-backend.ps1
```
