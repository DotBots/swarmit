# SPDX-FileCopyrightText: 2022-present Inria
# SPDX-FileCopyrightText: 2022-present Alexandre Abadie <alexandre.abadie@inria.fr>
#
# SPDX-License-Identifier: BSD-3-Clause

"""Logger module."""

import logging
import logging.config

import structlog


def setup_logging():
    """Setup logging."""
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.StackInfoRenderer(),
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
    ]

    structlog.configure(
        processors=processors,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    stdlib_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "logfmt": {
                "()": structlog.stdlib.ProcessorFormatter,
                "processor": structlog.processors.LogfmtRenderer(
                    key_order=["timestamp", "level", "logger", "event"],
                    drop_missing=True,
                ),
            },
            "rich": {
                "()": structlog.stdlib.ProcessorFormatter,
                "processor": structlog.dev.ConsoleRenderer(),
            },
        },
        "handlers": {
            "console": {
                "formatter": "rich",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stderr",
            }
        },
        "loggers": {
            "swarmit": {
                "handlers": ["console"],
                "level": logging.INFO,
                "propagate": True,
            },
        },
    }
    logging.config.dictConfig(stdlib_config)


LOGGER = structlog.get_logger("swarmit")
