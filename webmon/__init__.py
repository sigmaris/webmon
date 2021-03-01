def get_logging_config(loglevel):
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {"format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s"},
        },
        "handlers": {
            "default": {
                "level": loglevel,
                "formatter": "standard",
                "class": "logging.StreamHandler",
            },
        },
        "loggers": {
            "": {"handlers": ["default"], "level": loglevel, "propagate": False},
            "webmon": {"handlers": ["default"], "level": loglevel, "propagate": False},
            "kafka": {"handlers": ["default"], "level": "WARNING", "propagate": False},
        },
    }
