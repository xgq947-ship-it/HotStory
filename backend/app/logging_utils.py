from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

# uvicorn 自带的 logger 默认使用它自己的 Formatter，并且 propagate=False。
# 不接管它们，日志文件里就会混着 JSON 行和 "INFO:     127.0.0.1:... 200 OK"。
UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")
EXTRA_FIELDS = ("topic_id", "step", "provider", "duration_ms")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in EXTRA_FIELDS:
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str = "INFO", *, access_log: bool = False) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
    for name in UVICORN_LOGGERS:
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
    logging.getLogger("uvicorn.access").disabled = not access_log
