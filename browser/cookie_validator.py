import time
import sys
from playwright.sync_api import TimeoutError, Error as PlaywrightError


class CookieValidator:
    """Cookie validator, responsible for periodically verifying Cookie validity."""

    def __init__(self, page, context, logger):
        """
        Initialize Cookie validator.

        Args:
            page: Main page instance
            context: Browser context
            logger: Logger
        """
        self.page = page
        self.context = context
        self.logger = logger

    
    def validate_cookies_in_main_thread(self):
        """
        Execute Cookie validation in the main thread (called by main thread).

        Returns:
            bool: Whether the Cookie is valid
        """
        validation_page = None
        try:
            # Create a new tab (executed in the main thread)
            self.logger.info("Starting Cookie validation...")
            validation_page = self.context.new_page()

            # Visit validation URL
            validation_url = "https://aistudio.google.com/apps"
            validation_page.goto(validation_url, wait_until='domcontentloaded', timeout=30000)

            # Wait for page loading
            validation_page.wait_for_timeout(2000)

            # Get final URL
            final_url = validation_page.url

            # Check if redirected to login page
            if "accounts.google.com/v3/signin/identifier" in final_url:
                self.logger.error("Cookie validation failed: Redirected to login page")
                return False

            if "accounts.google.com/v3/signin/accountchooser" in final_url:
                self.logger.error("Cookie validation failed: Redirected to account selection page")
                return False

            # If no redirect to login page, consider it successful
            self.logger.info("Cookie validation successful")
            return True

        except TimeoutError:
            self.logger.error("Cookie validation failed: Page load timeout")
            return False

        except PlaywrightError as e:
            self.logger.error(f"Cookie validation failed: {e}")
            return False

        except Exception as e:
            self.logger.error(f"Cookie validation failed: {e}")
            return False

        finally:
            # Close validation tab
            if validation_page:
                try:
                    validation_page.close()
                except Exception:
                    pass  # Ignore closing errors

    def shutdown_instance_on_cookie_failure(self):
        """
        Shut down instance due to Cookie failure.
        """
        self.logger.error("Cookie invalid, shutting down instance")
        time.sleep(1)
        sys.exit(1)