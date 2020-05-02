import functools
import logging

# logger = logging.getLogger(__name__)

log_level = logging.INFO


def log_with(logger, name: str):
    def decorator(func):
        @functools.wraps(func)
        def inner(*args, **kwargs):
            logger.info(f"{name}: Starting...")
            ret = func(*args, **kwargs)
            logger.info(f"{name}: Done!")
            return ret

        return inner

    return decorator


def get_custom_logger(name: str):
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    return logger
