# Python Magic

## Local run (tool site + runner)

```powershell
py tool_site\server.py
```

Open: http://127.0.0.1:5179/

## Netlify deploy (frontend only)

This repository contains:
- `tool_site/` static frontend (deployable to Netlify)
- `tool_site/server.py` local backend that runs Python scripts (not runnable on Netlify)

To use the Netlify frontend with a remote backend, open the Netlify site with:

`/?api=https://YOUR_BACKEND_BASE_URL`

If the backend is protected with an API key, add:

`/?api=https://YOUR_BACKEND_BASE_URL&key=YOUR_API_KEY`

## Deploy backend (scripts run on server)

Netlify cannot run Python processes. Deploy the backend using Docker on a platform that supports containers.

### Option A: Render (Docker)

1. Go to Render → New → Web Service
2. Connect GitHub repo `zubbicodes/python_magic`
3. Render will detect `render.yaml` and the `Dockerfile`
4. Deploy, then copy the backend URL
5. Open your Netlify site with:
   `/?api=https://YOUR_RENDER_BACKEND_URL`

### Option B: Any VPS (Docker)

1. Install Docker on your server (Ubuntu recommended)
2. On the server:

```bash
git clone https://github.com/zubbicodes/python_magic.git
cd python_magic
docker build -t python-magic .
docker run -p 8080:8080 --restart unless-stopped python-magic
```

3. Put Nginx/Caddy in front for HTTPS, then use the same `/?api=` setting on the Netlify frontend.
