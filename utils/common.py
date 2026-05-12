"""
General utility functions.

Provides basic functionalities commonly used in the project.
"""

import os
import random
from datetime import datetime, timedelta
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


def get_next_refresh_time(min_hours=6, max_hours=10):
    """
    Calculate a random refresh time between min_hours and max_hours from now.
    """
    now = datetime.now()
    
    try:
        low = float(min_hours)
        high = float(max_hours)
    except (ValueError, TypeError):
        low, high = 6.0, 10.0

    # Sanity bounds: 1 hour to 24 hours
    low = max(1.0, min(low, 24.0))
    high = max(1.0, min(high, 24.0))

    if low > high:
        low, high = high, low
        
    try:
        random_hours = random.uniform(low, high)
        return now + timedelta(hours=random_hours)
    except (OverflowError, ValueError):
        # Fallback to a safe 8 hours if calculation fails
        return now + timedelta(hours=8)
