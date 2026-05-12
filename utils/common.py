"""
General utility functions.

Provides basic functionalities commonly used in the project.
"""

import os
from pathlib import Path

def clean_env_value(value):
    """
    Clean environment variable value, remove leading/trailing whitespace.

    Args:
        value: Original environment variable value

    Returns:
        str or None: Cleaned value, or None if empty/None
    """
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def parse_headless_mode(headless_setting):
    """
    Parse headless mode configuration.

    Args:
        headless_setting: Headless configuration value

    Returns:
        bool or str: True for headless, False for headed, 'virtual' for virtual mode
    """
    if str(headless_setting).lower() == 'true':
        return True
    elif str(headless_setting).lower() == 'false':
        return False
    else:
        return 'virtual'


def ensure_dir(path):
    """
    Ensure directory exists, create if it does not.

    Args:
        path: Directory path (can be string or Path object)
    """
    if isinstance(path, str):
        path = Path(path)
    os.makedirs(path, exist_ok=True)