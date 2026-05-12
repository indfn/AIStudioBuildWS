import logging
import datetime
import os

def custom_timezone_converter(timestamp):
    """
    Convert timestamp to struct_time in the specified timezone (default UTC+8/Asia/Shanghai).
    The timezone is configured via the TZ_OFFSET (hours) environment variable.
    """
    
    # Attempt to get offset from environment variable, default to 8 (Beijing time)
    try:
        offset_hours = float(os.getenv('TZ_OFFSET', 8))
    except (ValueError, TypeError):
        offset_hours = 8

    # 创建时区对象
    target_timezone = datetime.timezone(datetime.timedelta(hours=offset_hours))
    
    # 转换时间
    dt_time = datetime.datetime.fromtimestamp(timestamp, target_timezone)
    return dt_time.timetuple()

def setup_logging(log_file, prefix=None, level=logging.INFO):
    """
    Configure the logger to output to file and console.
    Supports an optional prefix for identifying log sources.

    Each call reconfigures handlers to accommodate multi-process environments.

    Time display defaults to UTC+8 (Beijing time), which can be modified via the TZ_OFFSET environment variable.

    :param log_file: Path to the log file.
    :param prefix: (Optional) A string prefix to add to the beginning of each log message.
    :param level: Log level.
    """
    logger = logging.getLogger('my_app_logger') 
    logger.setLevel(level)

    if logger.hasHandlers():
        logger.handlers.clear()

    base_format = '%(asctime)s - %(process)d - %(levelname)s - %(message)s'

    if prefix:
        log_format = f'%(asctime)s - %(process)d - %(levelname)s - {prefix} - %(message)s'
    else:
        log_format = base_format

    fh = logging.FileHandler(log_file)
    fh.setLevel(level)

    ch = logging.StreamHandler()
    ch.setLevel(level)

    formatter = logging.Formatter(log_format)
    # Set custom time converter
    formatter.converter = custom_timezone_converter

    fh.setFormatter(formatter)
    ch.setFormatter(formatter)

    logger.addHandler(fh)
    logger.addHandler(ch)
    
    logger.propagate = False
    
    return logger