"""
Unified Cookie Manager
Integrates detection, loading, and management functions for JSON file and environment variable cookies.
"""

import os
import json
from dataclasses import dataclass
from typing import List, Dict, Optional
from utils.paths import cookies_dir
from utils.cookie_handler import auto_convert_to_playwright
from utils.common import clean_env_value

@dataclass
class CookieSource:
    """Unified representation of Cookie source"""
    type: str  # "file" | "env_var"
    identifier: str  # filename or "USER_COOKIE_1"
    display_name: str  # Display name

    def __str__(self):
        return f"{self.type}:{self.identifier}"


class CookieManager:
    """
    Unified Cookie Manager
    Responsible for detecting, loading, and caching Cookie data from all sources.
    """

    def __init__(self, logger=None):
        self.logger = logger
        self._detected_sources: Optional[List[CookieSource]] = None
        self._cookie_cache: Dict[str, List[Dict]] = {}

    def detect_all_sources(self) -> List[CookieSource]:
        """
        Detect all available Cookie sources (JSON files + environment variables).
        Results are cached to avoid repeated scanning.
        """
        if self._detected_sources is not None:
            return self._detected_sources

        sources = []

        # 1. Scan JSON files in Cookies directory
        try:
            cookie_path = cookies_dir()
            if os.path.isdir(cookie_path):
                cookie_files = [f for f in os.listdir(cookie_path) if f.lower().endswith('.json')]

                for cookie_file in cookie_files:
                    source = CookieSource(
                        type="file",
                        identifier=cookie_file,
                        display_name=cookie_file
                    )
                    sources.append(source)

                if cookie_files and self.logger:
                    self.logger.info(f"Found {len(cookie_files)} Cookie files")
                elif self.logger:
                    self.logger.info(f"No Cookie files found in {cookie_path} directory")
            else:
                if self.logger:
                    self.logger.error(f"Cookie directory does not exist: {cookie_path}")

        except Exception as e:
            if self.logger:
                self.logger.error(f"Error scanning Cookie directory: {e}")

        # 2. Scan USER_COOKIE environment variables
        cookie_index = 1
        env_cookie_count = 0

        while True:
            env_var_name = f"USER_COOKIE_{cookie_index}"
            env_value = clean_env_value(os.getenv(env_var_name))

            if not env_value:
                if cookie_index == 1 and self.logger:
                    self.logger.info(f"No USER_COOKIE environment variables detected")
                break

            source = CookieSource(
                type="env_var",
                identifier=env_var_name,
                display_name=env_var_name
            )
            sources.append(source)

            env_cookie_count += 1
            cookie_index += 1

        if env_cookie_count > 0 and self.logger:
            self.logger.info(f"Found {env_cookie_count} Cookie environment variables")

        # Cache results
        self._detected_sources = sources
        return sources

    def load_cookies(self, source: CookieSource) -> List[Dict]:
        """
        Load Cookie data from specified source.

        Args:
            source: Cookie source object

        Returns:
            Playwright-compatible cookie list
        """
        cache_key = str(source)

        # Check cache
        if cache_key in self._cookie_cache:
            if self.logger:
                self.logger.debug(f"Loading Cookie from cache: {source.display_name}")
            return self._cookie_cache[cache_key]

        cookies = []

        try:
            if source.type == "file":
                cookies = self._load_from_file(source.identifier)
            elif source.type == "env_var":
                cookies = self._load_from_env(source.identifier)
            else:
                if self.logger:
                    self.logger.error(f"Unknown Cookie source type: {source.type}")
                return []

            # Cache results
            self._cookie_cache[cache_key] = cookies

            if self.logger:
                self.logger.info(f"Loaded {len(cookies)} Cookie data from {source.display_name}")

        except Exception as e:
            if self.logger:
                self.logger.error(f"Error loading Cookie from {source.display_name}: {e}")
            return []

        return cookies

    def _load_from_file(self, filename: str) -> List[Dict]:
        """Load Cookie from file, automatically recognize JSON or KV format"""
        cookie_path = cookies_dir() / filename

        if not os.path.exists(cookie_path):
            raise FileNotFoundError(f"Cookie file does not exist: {cookie_path}")

        with open(cookie_path, 'r', encoding='utf-8') as f:
            file_content = f.read().strip()

        # Attempt to parse as JSON
        try:
            cookies_from_file = json.loads(file_content)
            # JSON parsing successful, use automatic conversion function
            return auto_convert_to_playwright(
                cookies_from_file,
                default_domain=".google.com",
                logger=self.logger
            )
        except json.JSONDecodeError:
            # JSON parsing failed, handle as KV format
            if self.logger:
                self.logger.info(f"File {filename} is not in valid JSON format, attempting to parse as KV format")
            return auto_convert_to_playwright(
                file_content,
                default_domain=".google.com",
                logger=self.logger
            )

    def _load_from_env(self, env_var_name: str) -> List[Dict]:
        """Load Cookie from environment variable, automatically recognize JSON or KV format"""
        env_value = clean_env_value(os.getenv(env_var_name))

        if not env_value:
            raise ValueError(f"Environment variable {env_var_name} does not exist or is empty")

        # Attempt to parse as JSON
        try:
            cookies_from_env = json.loads(env_value)
            # JSON parsing successful, use automatic conversion function
            return auto_convert_to_playwright(
                cookies_from_env,
                default_domain=".google.com",
                logger=self.logger
            )
        except json.JSONDecodeError:
            # JSON parsing failed, handle as KV format
            if self.logger:
                self.logger.debug(f"Environment variable {env_var_name} is not in valid JSON format, parsing as KV format")
            return auto_convert_to_playwright(
                env_value,
                default_domain=".google.com",
                logger=self.logger
            )

    def save_cookies(self, source: CookieSource, cookies: list):
        """
        Save cookies back to their source if the source is a file.
        Write atomically using a temporary file.

        Args:
            source: CookieSource object representing where these cookies came from
            cookies: List of Playwright-compatible cookie dictionaries
        """
        if source.type != "file":
            if self.logger:
                self.logger.debug(f"Skipping save for non-file cookie source: {source.type}")
            return

        try:
            cookie_path = cookies_dir() / source.identifier
            tmp_path = cookie_path.with_suffix(".tmp")
            
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(cookies, f, indent=2)
            
            os.replace(tmp_path, cookie_path)
            
            # Update cache so next load gets the fresh cookies
            cache_key = str(source)
            self._cookie_cache[cache_key] = cookies
            
            if self.logger:
                self.logger.info(f"Successfully saved {len(cookies)} cookies to {source.identifier}")
        except Exception as e:
            if self.logger:
                self.logger.error(f"Error saving cookies to {source.identifier}: {e}")