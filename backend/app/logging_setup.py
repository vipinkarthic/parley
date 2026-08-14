"""Structured logs with a request id.

There was no logging configuration at all before this. The application's own
`logger.info` calls went to a root logger with no handler, so they were
dropped on the floor - including the "Parley API ready" line on boot, which
looked like it was working because uvicorn's own startup output arrived at the
same moment.

Production emits one JSON object per line. Render's log viewer is plain text
either way, but JSON survives being grepped, filtered and pasted into
something that parses it, and it keeps the request id attached to every line
rather than only to the ones someone remembered to format it into.
Development keeps a human-readable line, because reading JSON by eye while
debugging is a tax with no return.

Chosen over Prometheus / Grafana deliberately: at one instance and a handful
of concurrent meetings, structured logs answer the questions that get asked.
"""
import json
import logging
import os
import sys
from contextvars import ContextVar

from .config import IS_PRODUCTION

# Set per request by the middleware and read by the filter below, so every
# line logged while handling a request carries it without being passed down
# through every function call.
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

# Fields already on a LogRecord; anything else in __dict__ was put there by a
# caller passing `extra=` and belongs in the JSON output.
_RESERVED = frozenset(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__
) | {"request_id", "asctime", "message", "taskName"}


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = request_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    fmt = os.getenv("LOG_FORMAT", "json" if IS_PRODUCTION else "text").lower()
    level = os.getenv("LOG_LEVEL", "INFO").upper()

    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RequestIdFilter())
    handler.setFormatter(
        JsonFormatter()
        if fmt == "json"
        else logging.Formatter(
            "%(asctime)s %(levelname)-7s [%(request_id)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )
    )

    root = logging.getLogger()
    # Replace rather than add: uvicorn installs its own handlers, and keeping
    # both means every line appears twice in the deploy logs.
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level)

    for name in ("uvicorn", "uvicorn.error"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True

    # The middleware logs a richer line for the same request, with the id and
    # a duration attached. Two lines per request that disagree about their
    # format is worse than one.
    logging.getLogger("uvicorn.access").disabled = True
