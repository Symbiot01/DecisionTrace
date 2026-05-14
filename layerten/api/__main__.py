import logging
import os

import uvicorn

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

# reload kills in-memory pipeline jobs — off by default for long fetch/process runs
_reload = os.getenv("UVICORN_RELOAD", "0") == "1"

uvicorn.run(
    "layerten.api.main:app",
    host="0.0.0.0",
    port=8000,
    reload=_reload,
    reload_dirs=["layerten"] if _reload else None,
)
