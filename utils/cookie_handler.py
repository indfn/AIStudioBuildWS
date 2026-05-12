def convert_cookie_editor_to_playwright(cookies_from_editor, logger=None):
    """
    Convert Cookie list exported from Cookie-Editor plugin to Playwright compatible format.
    """
    playwright_cookies = []

    for cookie in cookies_from_editor:
        pw_cookie = {}
        for key in ['name', 'value', 'domain', 'path', 'httpOnly', 'secure']:
            if key in cookie:
                pw_cookie[key] = cookie[key]
        if cookie.get('session', False):
            pw_cookie['expires'] = -1
        elif 'expirationDate' in cookie:
            if cookie['expirationDate'] is not None:
                pw_cookie['expires'] = int(cookie['expirationDate'])
            else:
                pw_cookie['expires'] = -1

        if 'sameSite' in cookie:
            same_site_value = str(cookie['sameSite']).lower()
            if same_site_value == 'no_restriction':
                pw_cookie['sameSite'] = 'None'
            elif same_site_value in ['lax', 'strict']:
                pw_cookie['sameSite'] = same_site_value.capitalize()
            elif same_site_value == 'unspecified':
                pw_cookie['sameSite'] = 'Lax'

        if all(key in pw_cookie for key in ['name', 'value', 'domain', 'path']):
            playwright_cookies.append(pw_cookie)
        else:
            if logger:
                logger.warning(f"Skipping an incomplete Cookie: {cookie}")

    return playwright_cookies


def convert_kv_to_playwright(kv_string, default_domain=".google.com", logger=None):
    """
    Convert key-value pair format Cookie string to Playwright compatible format.

    Args:
        kv_string (str): Cookie key-value pair string, format "name1=value1; name2=value2; ..."
        default_domain (str): Default domain, default is ".google.com"
        logger: Logger

    Returns:
        list: Playwright compatible Cookie list
    """
    playwright_cookies = []

    # Split Cookies by semicolon
    cookie_pairs = kv_string.split(';')

    for pair in cookie_pairs:
        pair = pair.strip()  # Remove leading/trailing whitespace

        if not pair:  # Skip empty strings
            continue

        # Skip invalid Cookie (does not contain equal sign)
        if '=' not in pair:
            if logger:
                logger.warning(f"Skipping invalid Cookie format: '{pair}'")
            continue

        # Split name and value
        name, value = pair.split('=', 1)  # Only split on first equal sign
        name = name.strip()
        value = value.strip()

        if not name:  # Skip empty names
            if logger:
                logger.warning(f"Skipping Cookie with empty name: '{pair}'")
            continue

        # Construct Playwright formatted Cookie
        pw_cookie = {
            'name': name,
            'value': value,
            'domain': default_domain,
            'path': '/',
            'expires': -1,  # Default to session Cookie
            'httpOnly': False,  # KV format cannot determine httpOnly status, default to False
            'secure': True,     # Assume secure Cookie
            'sameSite': 'Lax'   # Default SameSite policy
        }

        playwright_cookies.append(pw_cookie)

        if logger:
            logger.debug(f"Successfully converted Cookie: {name} -> domain={default_domain}")

    return playwright_cookies


def auto_convert_to_playwright(cookie_data, default_domain=".google.com", logger=None):
    """
    Automatically detect Cookie data format and convert to Playwright compatible format.
    Supports two input formats:
    1. JSON array (Cookie-Editor export format)
    2. KV string (Key-value pair format: "name1=value1; name2=value2; ...")

    Args:
        cookie_data: Cookie data, can be list (JSON format) or str (KV format)
        default_domain (str): Default domain used for KV format, default is ".google.com"
        logger: Logger

    Returns:
        list: Playwright compatible Cookie list

    Raises:
        ValueError: Thrown when format cannot be identified
    """
    # Format 1: JSON array format (Cookie-Editor export format)
    if isinstance(cookie_data, list):
        if logger:
            logger.debug(f"JSON array format Cookie data detected, total {len(cookie_data)} entries")
        return convert_cookie_editor_to_playwright(cookie_data, logger=logger)

    # Format 2: KV string format
    if isinstance(cookie_data, str):
        # Remove leading/trailing whitespace
        cookie_str = cookie_data.strip()

        if not cookie_str:
            if logger:
                logger.warning("Empty Cookie string received")
            return []

        if logger:
            logger.debug(f"KV string format Cookie data detected")

        return convert_kv_to_playwright(
            cookie_str,
            default_domain=default_domain,
            logger=logger
        )

    # Unrecognized format
    error_msg = f"Unrecognized Cookie data format: {type(cookie_data).__name__}"
    if logger:
        logger.error(error_msg)
    raise ValueError(error_msg)
