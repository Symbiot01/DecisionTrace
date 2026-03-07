import logging
import uvicorn

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
uvicorn.run("layerten.api.main:app", host="0.0.0.0", port=8000, reload=True)
