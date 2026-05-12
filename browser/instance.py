import os
import signal
import time
import threading
from datetime import datetime
from playwright.sync_api import TimeoutError, Error as PlaywrightError
from utils.logger import setup_logging
from utils.cookie_manager import CookieManager
from browser.navigation import handle_successful_navigation, KeepAliveError, handle_popup_dialog
from browser.cookie_validator import CookieValidator
from camoufox.sync_api import Camoufox
from utils.paths import logs_dir
from utils.common import parse_headless_mode, ensure_dir, get_next_refresh_time
from utils.url_helper import extract_url_path, mask_url_for_logging, mask_path_for_logging

def _cookie_sync_loop(context, cookie_manager, cookie_source, logger, shutdown_event, page=None):
    """Background daemon thread to perform scheduled refreshes and save new cookies"""
    
    # Initialize refresh timing from intervals (in hours)
    refresh_min = os.getenv("REFRESH_INTERVAL_MIN", "6")
    refresh_max = os.getenv("REFRESH_INTERVAL_MAX", "10")
    spinner_timeout_ms = int(os.getenv("SPINNER_TIMEOUT_MS", "300000"))
    
    next_refresh = get_next_refresh_time(refresh_min, refresh_max)
    logger.info(f"Probabilistic refresh scheduled for: {next_refresh.strftime('%Y-%m-%d %H:%M:%S')}")

    while not (shutdown_event and shutdown_event.is_set()):
        # Critical: check if the page associated with THIS thread is still active
        if not page or page.is_closed():
            logger.info("Associated page is closed. Terminating background refresh thread.")
            break

        try:
            # Check if it's time to refresh
            now = datetime.now()
            if now >= next_refresh:
                logger.info("Scheduled refresh time reached. Checking for active generation...")
                
                try:
                    # Smart Wait: Check for mat-spinner
                    spinner_locator = page.locator('mat-spinner')
                    
                    # If spinner is visible, wait for it to disappear
                    # Use a very short timeout for the initial check to avoid blocking
                    try:
                        is_generating = spinner_locator.is_visible(timeout=500)
                    except:
                        is_generating = False

                    if is_generating:
                        logger.info("Generation active (spinner visible). Waiting for it to finish before refresh...")
                        try:
                            # Wait for generation to finish or timeout
                            spinner_locator.wait_for(state='hidden', timeout=spinner_timeout_ms)
                            logger.info("Generation finished. Waiting 2 seconds for stability...")
                            time.sleep(2)
                        except TimeoutError:
                            logger.warning(f"Spinner wait timed out ({spinner_timeout_ms/1000}s). Proceeding with refresh anyway to avoid session expiry.")
                    
                    # Re-verify page is still open before navigation
                    if page.is_closed():
                        break

                    # Perform page reload
                    logger.info("Reloading page to refresh authentication...")
                    page.reload(wait_until='domcontentloaded', timeout=90000)
                    
                    # Wait for loading indicator (spinner) to disappear (initial page load spinner)
                    try:
                        spinner_locator.wait_for(state='hidden', timeout=30000)
                    except TimeoutError:
                        logger.warning("Loading indicator did not disappear after refresh reload, proceeding anyway")
                    
                    # Handle any popups that might have reappeared
                    handle_popup_dialog(page, logger=logger)
                    
                    # Save fresh cookies ONLY after refresh
                    cookies = context.cookies()
                    cookie_manager.save_cookies(cookie_source, cookies)
                    logger.info(f"Auth refresh successful: Saved {len(cookies)} new cookies")
                        
                except Exception as refresh_e:
                    if "Target closed" in str(refresh_e) or "context or browser has been closed" in str(refresh_e):
                        logger.info("Browser target closed during refresh. Thread exiting.")
                        break
                    logger.error(f"Error during scheduled auth refresh: {refresh_e}")
                
                # Calculate next refresh time (interval based)
                next_refresh = get_next_refresh_time(refresh_min, refresh_max)
                logger.info(f"Next probabilistic refresh scheduled for: {next_refresh.strftime('%Y-%m-%d %H:%M:%S')}")

            # Sleep in small chunks so we can exit quickly on shutdown or page close
            for _ in range(10): # Check every second for responsiveness
                if (shutdown_event and shutdown_event.is_set()) or page.is_closed():
                    break
                time.sleep(1)
                
        except Exception as e:
            if "Target closed" in str(e):
                break
            logger.error(f"Error in refresh loop: {e}")
            time.sleep(30)





def run_browser_instance(config, shutdown_event=None):
    """
    根据最终合并的配置，启动并管理一个单独的 Camoufox 浏览器实例。
    使用CookieManager统一管理Cookie加载，避免重复的扫描逻辑。
    """
    # Reset signal handler, ensure sub-process can respond to SIGTERM
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    # Ignore SIGINT (Ctrl+C), let main process handle it
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    cookie_source = config.get('cookie_source')
    if not cookie_source:
        # Use default logger for error reporting
        logger = setup_logging(os.path.join(logs_dir(), 'app.log'))
        logger.error("Error: cookie_source object missing in configuration")
        return

    instance_label = cookie_source.display_name
    logger = setup_logging(
        os.path.join(logs_dir(), 'app.log'), prefix=instance_label
    )
    diagnostic_tag = instance_label.replace(os.sep, "_")

    expected_url = config.get('url')
    proxy = config.get('proxy')
    headless_setting = config.get('headless', 'virtual')

    # Use CookieManager to load Cookies
    cookie_manager = CookieManager(logger)
    all_cookies = []

    try:
        # Load Cookies directly using CookieSource object
        cookies = cookie_manager.load_cookies(cookie_source)
        all_cookies.extend(cookies)

    except Exception as e:
        logger.error(f"Error loading from Cookie source: {e}")
        return

    # 3. Check if any Cookies are available
    if not all_cookies:
        logger.error("Error: No available Cookies (neither valid JSON files nor environment variables)")
        return

    cookies = all_cookies

    headless_mode = parse_headless_mode(headless_setting)
    launch_options = {"headless": headless_mode}
    # launch_options["block_images"] = True  # Disable image loading
    
    if proxy:
        logger.info(f"Using proxy: {proxy} to access")
        launch_options["proxy"] = {"server": proxy, "bypass": "localhost, 127.0.0.1"}
    
    screenshot_dir = logs_dir()
    ensure_dir(screenshot_dir)

    # Restart control variables
    max_retries = int(os.getenv("MAX_RESTART_RETRIES", "5"))
    retry_count = 0
    base_delay = 3

    while True:
        # Check if global shutdown signal received
        if shutdown_event and shutdown_event.is_set():
            logger.info("Global shutdown event detected, browser instance will not start, preparing to exit")
            return

        try:
            with Camoufox(**launch_options) as browser:
                context = browser.new_context()
                context.add_cookies(cookies)
                page = context.new_page()

                # Start background refresh thread
                sync_thread = threading.Thread(
                    target=_cookie_sync_loop,
                    args=(context, cookie_manager, cookie_source, logger, shutdown_event, page),
                    daemon=True
                )
                sync_thread.start()

                # Create Cookie validator
                cookie_validator = CookieValidator(page, context, logger)

                ####################################################################
                ############ Enhanced page.goto() error handling and logging ###############
                ####################################################################
                
                response = None
                try:
                    logger.info(f"Navigating to: {mask_url_for_logging(expected_url)} (timeout set to 90 seconds)")
                    # page.goto() returns a response object, we can use it to get status codes, etc.
                    response = page.goto(expected_url, wait_until='domcontentloaded', timeout=90000)
                    
                    # Check HTTP response status code
                    if response:
                        logger.info(f"Navigation partially successful, server response status code: {response.status} {response.status_text}")
                        if not response.ok: # response.ok checks if status code is in 200-299 range
                            logger.warning(f"Warning: Page loaded successfully, but HTTP status code indicates an error: {response.status}")
                            # Save snapshot for analysis even if status code is wrong
                            page.screenshot(path=os.path.join(screenshot_dir, f"WARN_http_status_{response.status}_{diagnostic_tag}.png"))
                    else:
                        # For non-http/https navigation (like about:blank), response might be None
                        logger.warning("page.goto did not return a response object, possibly a non-HTTP navigation")

                except TimeoutError:
                    # Most common error: timeout
                    logger.error(f"Navigation to {mask_url_for_logging(expected_url)} timed out (exceeded 90 seconds)")
                    logger.error("Possible reasons: slow network connection, target website server not responding, proxy issues, or page resources blocked")
                    # Attempt to save diagnostic info
                    try:
                        # Screenshot is helpful for seeing what state the page is stuck in (e.g., blank, loading, Chrome error page)
                        screenshot_path = os.path.join(screenshot_dir, f"FAIL_timeout_{diagnostic_tag}.png")
                        page.screenshot(path=screenshot_path, full_page=True)
                        logger.info(f"Captured screenshot at timeout: {screenshot_path}")
                        
                        # Saving HTML helps analyze DOM structure, useful even in headless mode
                        html_path = os.path.join(screenshot_dir, f"FAIL_timeout_{diagnostic_tag}.html")
                        with open(html_path, 'w', encoding='utf-8') as f:
                            f.write(page.content())
                        logger.info(f"Saved page HTML at timeout: {html_path}")
                    except Exception as diag_e:
                        logger.error(f"Additional error occurred while attempting timeout diagnosis (screenshot/saving HTML): {diag_e}")
                    return # Further operations are meaningless after timeout, terminate immediately

                except PlaywrightError as e:
                    # Catch other Playwright related network errors, e.g., DNS resolution failure, connection refused, etc.
                    error_message = str(e)
                    logger.error(f"Playwright network error occurred while navigating to {mask_url_for_logging(expected_url)}")
                    logger.error(f"Error details: {error_message}")
                    
                    # Playwright error messages are usually specific, e.g., "net::ERR_CONNECTION_REFUSED"
                    if "net::ERR_NAME_NOT_RESOLVED" in error_message:
                        logger.error("Troubleshooting suggestion: Check DNS settings or if the domain is correct")
                    elif "net::ERR_CONNECTION_REFUSED" in error_message:
                        logger.error("Troubleshooting suggestion: Target server might be down, or proxy/firewall blocked the connection")
                    elif "net::ERR_INTERNET_DISCONNECTED" in error_message:
                        logger.error("Troubleshooting suggestion: Check local network connection")
                    
                    # Similarly, try to take a screenshot, although page might be completely inaccessible
                    try:
                        screenshot_path = os.path.join(screenshot_dir, f"FAIL_network_error_{diagnostic_tag}.png")
                        page.screenshot(path=screenshot_path)
                        logger.info(f"Captured screenshot at network error: {screenshot_path}")
                    except Exception as diag_e:
                        logger.error(f"Additional error occurred while attempting network error diagnosis (screenshot): {diag_e}")
                    return # Network error, terminate

                # --- Continue execution if navigation didn't throw an exception ---
                
                logger.info("Page initial load complete, checking and handling initial popups...")
                page.wait_for_timeout(2000)
                
                final_url = page.url
                logger.info(f"Navigation complete. Final URL: {mask_url_for_logging(final_url)}")

                # ... Your original URL check logic remains unchanged ...
                if "accounts.google.com/v3/signin/identifier" in final_url:
                    logger.error("Google login page detected (email input required). Cookie completely invalid")
                    page.screenshot(path=os.path.join(screenshot_dir, f"FAIL_identifier_page_{diagnostic_tag}.png"))
                    return

                # Extract path part for matching (allows domain redirection)
                expected_path = extract_url_path(expected_url).split('?')[0]
                final_path = extract_url_path(final_url)

                if expected_path and expected_path in final_path:
                    logger.info(f"URL validation passed. Expected path: {mask_path_for_logging(expected_path)}")

                    # --- New robust strategy: wait for loading indicator to disappear ---
                    # Key to solving race conditions. Error messages or content only appear after initial load is finished.
                    spinner_locator = page.locator('mat-spinner')
                    try:
                        logger.info("Waiting for loading indicator (spinner) to disappear... (waiting up to 30 seconds)")
                        # Wait for spinner to become 'hidden' or disappear from DOM
                        spinner_locator.wait_for(state='hidden', timeout=30000)
                        logger.info("Loading indicator disappeared. Page async loading complete")
                    except TimeoutError:
                        logger.error("Page loading indicator did not disappear within 30 seconds. Page might be stuck")
                        page.screenshot(path=os.path.join(screenshot_dir, f"FAIL_spinner_stuck_{diagnostic_tag}.png"))
                        raise KeepAliveError("Page loading indicator timed out")

                    # --- Now we can safely check for error messages ---
                    # Use most specific text to avoid misjudgment
                    auth_error_text = "authentication error"
                    auth_error_locator = page.get_by_text(auth_error_text, exact=False)

                    # Use short timeout here as page should be stable
                    if auth_error_locator.is_visible(timeout=2000):
                        logger.error(f"Auth failure error banner detected: '{auth_error_text}'. Cookie expired or invalid")
                        screenshot_path = os.path.join(screenshot_dir, f"FAIL_auth_error_banner_{diagnostic_tag}.png")
                        page.screenshot(path=screenshot_path)
                        
                        # html_path = os.path.join(screenshot_dir, f"FAIL_auth_error_banner_{diagnostic_tag}.html")
                        # with open(html_path, 'w', encoding='utf-8') as f:
                        #     f.write(page.content())
                        # logger.info(f"Saved page HTML with error info: {html_path}")
                        return # Explicit failure, exit.

                    # --- If no error, final confirmation (as fallback) ---
                    logger.info("No auth error banner detected. Proceeding to final confirmation")
                    login_button_cn = page.get_by_role('button', name='登录')
                    login_button_en = page.get_by_role('button', name='Login')
                    
                    if login_button_cn.is_visible(timeout=1000) or login_button_en.is_visible(timeout=1000):
                        logger.error("'Login' button still displayed on page. Cookie invalid")
                        page.screenshot(path=os.path.join(screenshot_dir, f"FAIL_login_button_visible_{diagnostic_tag}.png"))
                        return

                    # --- If all checks pass, assume success ---
                    logger.info("All validations passed, confirmed successful login")

                    handle_successful_navigation(page, logger, diagnostic_tag, shutdown_event, cookie_validator)
                elif "accounts.google.com/v3/signin/accountchooser" in final_url:
                    logger.warning("Google account selection page detected. Login failed or Cookie expired")
                    page.screenshot(path=os.path.join(screenshot_dir, f"FAIL_chooser_click_failed_{diagnostic_tag}.png"))
                    return
                else:
                    logger.error(f"Navigated to unexpected URL")
                    logger.error(f"  Expected path: {mask_path_for_logging(expected_path)}")
                    logger.error(f"  Final path: {mask_path_for_logging(final_path)}")
                    logger.error(f"  Final URL: {mask_url_for_logging(final_url)}")
                    page.screenshot(path=os.path.join(screenshot_dir, f"FAIL_unexpected_url_{diagnostic_tag}.png"))
                    return

                # If running to here without exception, instance finished normally (e.g., received shutdown signal)
                # Reset retry counter upon normal finish
                retry_count = 0

                # Final cookie save BEFORE context closes
                try:
                    final_cookies = context.cookies()
                    cookie_manager.save_cookies(cookie_source, final_cookies)
                    logger.info("Saved final cookies before closing context")
                except Exception as e:
                    logger.error(f"Error during final cookie save: {e}")
                    
                return

        except KeepAliveError as e:
            retry_count += 1
            if retry_count > max_retries:
                logger.error(f"Retry limit reached ({max_retries}), instance will not restart, exiting")
                return
            
            # Exponential backoff: 3s, 6s, 12s, 24s... max 60s
            delay = min(base_delay * (2 ** (retry_count - 1)), 60)
            logger.error(f"Browser instance error (retry {retry_count}/{max_retries}), browser instance will restart in {delay} seconds: {e}")
            time.sleep(delay)
            continue
        except KeyboardInterrupt:
            logger.info(f"User interrupt, shutting down...")
            return
        except SystemExit as e:
            # Catch system exit upon Cookie validation failure
            if e.code == 1:
                logger.error("Cookie validation failed, closing process instance")
            else:
                logger.info(f"Instance exited normally, exit code: {e.code}")
            return
        except Exception as e:
            # Final catch for all unexpected errors
            logger.exception(f"Unexpected serious error occurred while running Camoufox instance: {e}")
            return
        finally:
            # Main process loop exited or shutdown signal received
            logger.info("Browser instance main loop terminated")
