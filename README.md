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
