"""
URL processing helper functions.

Provides URL parsing and path extraction functionality, used for domain-agnostic matching in navigation validation.
"""

from urllib.parse import urlparse


def extract_url_path(url: str) -> str:
    """
    Extract the path and query parameter portion of the URL, ignoring protocol and domain differences.

    Used to verify whether navigation reached the correct page, allowing for domain redirection.

    Args:
        url: Complete URL string

    Returns:
        path + query parameters + fragment (e.g.: "/apps/drive/123?param=value#section")
        If URL is empty or invalid, return empty string

    Examples:
        >>> extract_url_path("https://ai.studio/apps/drive/123?param=value")
        '/apps/drive/123?param=value'

        >>> extract_url_path("https://aistudio.google.com/apps/drive/123")
        '/apps/drive/123'

        >>> extract_url_path("https://example.com/path")
        '/path'
    """
    if not url:
        return ""

    try:
        parsed = urlparse(url)
        result = parsed.path
        if parsed.query:
            result += '?' + parsed.query
        if parsed.fragment:
            result += '#' + parsed.fragment
        return result
    except Exception:
        # Return empty string if URL format is invalid
        return ""


def mask_path_for_logging(path: str) -> str:
    """
    Mask the path for logging purposes.

    Masking rule:
    1. For /apps/drive/XXXXXXXXXX paths, keep first 4 and last 4 characters, replacing the middle with ***
    2. If it is not a /apps/drive/XXXXXXXXXX path, return the full path

    Args:
        path: URL path string

    Returns:
        Masked path string

    Examples:
        >>> mask_path_for_logging("/apps/drive/abcdef123456")
        '/apps/drive/abcd***3456'

        >>> mask_path_for_logging("/apps/drive/xyz789")
        '/apps/drive/xyz789'

        >>> mask_path_for_logging("/other/path")
        '/other/path'
    """
    if not path:
        return ""

    # Check if it is a /apps/drive/ path
    if path.startswith('/apps/drive/'):
        # Extract ID part of path
        path_parts = path.split('/')
        if len(path_parts) >= 4:  # ['', 'apps', 'drive', 'ID']
            drive_id = path_parts[3]

            # Perform masking if ID length > 8
            if len(drive_id) > 8:
                # Use same format as URL masking
                masked_id = f"{drive_id[:4]}***{drive_id[-4:]}"
                # Reconstruct path
                masked_parts = path_parts[:3] + [masked_id] + path_parts[4:]
                return '/'.join(masked_parts)

    # Return original path if it doesn't meet masking conditions
    return path


def mask_url_for_logging(url: str) -> str:
    """
    Mask the URL for logging purposes.

    Masking rule:
    1. For /apps/drive/XXXXXXXXXX paths, keep first 4 and last 4 characters, replacing the middle with ***
    2. If it is not a /apps/drive/XXXXXXXXXX path, return the full URL

    Args:
        url: Complete URL string

    Returns:
        Masked URL string

    Examples:
        >>> mask_url_for_logging("https://ai.studio/apps/drive/abcdef123456")
        'https://ai.studio/apps/drive/abcd***3456'

        >>> mask_url_for_logging("https://aistudio.google.com/apps/drive/xyz789")
        'https://aistudio.google.com/apps/drive/xyz789'

        >>> mask_url_for_logging("https://example.com/other/path")
        'https://example.com/other/path'
    """
    if not url:
        return ""

    try:
        parsed = urlparse(url)

        # Check if it is a /apps/drive/ path
        if parsed.path.startswith('/apps/drive/'):
            # Extract ID part of path
            path_parts = parsed.path.split('/')
            if len(path_parts) >= 4:  # ['', 'apps', 'drive', 'ID']
                drive_id = path_parts[3]

                # Perform masking if ID length > 8
                if len(drive_id) > 8:
                    masked_id = f"{drive_id[:4]}***{drive_id[-4:]}"
                    # Reconstruct path
                    masked_parts = path_parts[:3] + [masked_id] + path_parts[4:]
                    masked_path = '/'.join(masked_parts)

                    # Reconstruct URL
                    result = f"{parsed.scheme}://{parsed.netloc}{masked_path}"
                    if parsed.query:
                        result += '?' + parsed.query
                    if parsed.fragment:
                        result += '#' + parsed.fragment
                    return result

        # Return original URL if it doesn't meet masking conditions
        return url

    except Exception:
        # Return original URL if parsing fails
        return url
