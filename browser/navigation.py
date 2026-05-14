import time
import os
from datetime import datetime, timezone, timedelta
from playwright.sync_api import Page, TimeoutError
from utils.paths import logs_dir
from utils.common import ensure_dir, compute_next_refresh, format_time, format_duration
from utils.url_helper import mask_url_for_logging, mask_path_for_logging, extract_url_path
from browser.ws_helper import get_ws_status, dismiss_interaction_modal, click_in_iframe

class KeepAliveError(Exception):
    pass

def handle_popup_dialog(page: Page, logger=None):
    logger.info("Starting popup processing...")
    
    button_names = ["Skip", "Next", "Try it out", "Got it", "Dismiss", "Continue to the app"]
    max_iterations = 10
    total_clicks = 0
    
    try:
        for iteration in range(max_iterations):
            clicked_in_round = False
            time.sleep(1)
            
            for name in button_names:
                try:
                    btn = page.locator(f'button:visible:has-text("{name}")').first
                    if btn.count() > 0 and btn.is_visible():
                        btn.click(force=True, timeout=2000)
                        total_clicks += 1
                        clicked_in_round = True
                        time.sleep(1)
                except:
                    pass
            
            try:
                frame = page.frame_locator('iframe[title="Preview"]')
                for name in button_names:
                    try:
                        btn = frame.locator(f'button:visible:has-text("{name}")').first
                        if btn.count() > 0 and btn.is_visible():
                            btn.click(force=True, timeout=2000)
                            total_clicks += 1
                            clicked_in_round = True
                            time.sleep(1)
                    except:
                        pass
            except:
                pass
            
            try:
                close_btn = page.locator('[aria-label="Close"]').first
                if close_btn.count() > 0 and close_btn.is_visible(timeout=300):
                    close_btn.click(timeout=2000)
                    total_clicks += 1
                    clicked_in_round = True
                    time.sleep(1)
            except:
                pass
            
            if not clicked_in_round:
                try:
                    page.keyboard.press("Escape")
                except:
                    pass
            
            if not clicked_in_round:
                break
        
        if total_clicks > 0:
            logger.info(f"Popup processing complete, clicked {total_clicks} times in total")
        else:
            logger.info("No popup detected")
    except Exception as e:
        logger.info(f"Unexpected error while checking for popups: {e}, will continue execution...")


def _do_scheduled_refresh(page, context, cookie_manager, cookie_source, logger, expected_url, refresh_min, refresh_max):
    """Perform a full auth refresh: pre-flight guard, reload, validate, save cookies.
    Returns the next refresh datetime, or schedules a 5min retry on failure."""
    screenshot_dir = logs_dir()

    # --- Pre-flight: sanity check current page ---
    try:
        current_url = page.url

        bad_patterns = [
            "accounts.google.com/v3/signin/identifier",
            "accounts.google.com/v3/signin/accountchooser",
            "google.com/sorry",
        ]
        if any(p in current_url for p in bad_patterns):
            logger.warning(f"Skipping refresh: page is on login/error page. URL: {mask_url_for_logging(current_url)}")
            return datetime.now(timezone.utc) + timedelta(minutes=5)

        if expected_url:
            expected_path = extract_url_path(expected_url).split('?')[0]
            current_path = extract_url_path(current_url)
            if expected_path and expected_path not in current_path:
                logger.warning(f"Skipping refresh: unexpected URL path. Expected: {mask_path_for_logging(expected_path)}, Got: {mask_path_for_logging(current_path)}")
                return datetime.now(timezone.utc) + timedelta(minutes=5)
    except Exception as e:
        logger.warning(f"Page state check failed, scheduling quick retry: {e}")
        return datetime.now(timezone.utc) + timedelta(minutes=5)

    # --- Snapshot cookies before reload ---
    try:
        before = {c['name']: c for c in context.cookies()}
    except:
        before = {}

    # --- Reload page ---
    try:
        logger.info("Reloading page to refresh authentication...")
        page.reload(wait_until='domcontentloaded', timeout=90000)
    except Exception as e:
        if "Target closed" in str(e) or "context or browser has been closed" in str(e):
            raise
        logger.error(f"Page reload failed: {e}")
        return datetime.now(timezone.utc) + timedelta(minutes=5)

    # --- Post-reload: wait for loading indicator ---
    try:
        spinner_locator = page.locator('mat-spinner').first
        try:
            spinner_locator.wait_for(state='hidden', timeout=30000)
        except TimeoutError:
            logger.warning("Loading indicator did not disappear after refresh reload, proceeding anyway")
    except:
        pass

    # --- Post-reload: validate page state (same checks as initial navigation) ---
    try:
        final_url = page.url
        logger.info(f"Post-reload URL: {mask_url_for_logging(final_url)}")

        if "accounts.google.com/v3/signin/identifier" in final_url:
            logger.error("Login page detected after reload — cookie refresh failed")
            page.screenshot(path=os.path.join(screenshot_dir, f"FAIL_refresh_login_{cookie_source.display_name}.png"))
            return datetime.now(timezone.utc) + timedelta(minutes=5)

        if "accounts.google.com/v3/signin/accountchooser" in final_url:
            logger.warning("Account chooser detected after reload — cookie refresh failed")
            page.screenshot(path=os.path.join(screenshot_dir, f"FAIL_refresh_chooser_{cookie_source.display_name}.png"))
            return datetime.now(timezone.utc) + timedelta(minutes=5)

        if expected_url:
            expected_path = extract_url_path(expected_url).split('?')[0]
            final_path = extract_url_path(final_url)
            if expected_path and expected_path not in final_path:
                logger.error(f"Unexpected URL after reload. Expected: {mask_path_for_logging(expected_path)}, Got: {mask_path_for_logging(final_path)}")
                page.screenshot(path=os.path.join(screenshot_dir, f"FAIL_refresh_url_{cookie_source.display_name}.png"))
                return datetime.now(timezone.utc) + timedelta(minutes=5)

        # Check for auth error banner
        auth_error_text = "authentication error"
        if page.get_by_text(auth_error_text, exact=False).is_visible(timeout=2000):
            logger.error(f"Auth error banner detected after reload — cookie refresh failed")
            page.screenshot(path=os.path.join(screenshot_dir, f"FAIL_refresh_auth_{cookie_source.display_name}.png"))
            return datetime.now(timezone.utc) + timedelta(minutes=5)

        # Check for login button
        if page.get_by_role('button', name='登录').is_visible(timeout=1000) or \
           page.get_by_role('button', name='Login').is_visible(timeout=1000):
            logger.error("Login button visible after reload — cookie refresh failed")
            page.screenshot(path=os.path.join(screenshot_dir, f"FAIL_refresh_login_btn_{cookie_source.display_name}.png"))
            return datetime.now(timezone.utc) + timedelta(minutes=5)

        logger.info("Post-reload validation passed — cookies are valid")
    except Exception as e:
        logger.warning(f"Post-reload validation error: {e}")
        return datetime.now(timezone.utc) + timedelta(minutes=5)

    # --- Handle popups after validation ---
    try:
        handle_popup_dialog(page, logger=logger)
    except:
        pass

    # --- Save fresh cookies (only if validation passed) ---
    try:
        cookies = context.cookies()
        cookie_manager.save_cookies(cookie_source, cookies)
    except Exception as e:
        logger.error(f"Failed to save cookies after refresh: {e}")
        return datetime.now(timezone.utc) + timedelta(minutes=5)

    # --- Cookie diff ---
    if before and cookies:
        after = {c['name']: c for c in cookies}
        now_ts = time.time()
        for name in sorted(after):
            ac = after[name]
            if name in before:
                bc = before[name]
                if bc.get('value') != ac.get('value'):
                    logger.info(f"  Cookie '{name}': value changed")
                bc_exp, ac_exp = bc.get('expires'), ac.get('expires')
                if bc_exp and ac_exp and ac_exp > bc_exp:
                    gained = (ac_exp - bc_exp) / 3600
                    logger.info(f"  Cookie '{name}': expiry extended by {gained:.1f}h")
            else:
                logger.info(f"  Cookie '{name}': NEW")
        for name in sorted(before):
            if name not in after:
                logger.info(f"  Cookie '{name}': DELETED")

        ttl_hours = []
        for c in cookies:
            exp = c.get('expires')
            if exp and exp > now_ts:
                ttl_hours.append(((exp - now_ts) / 3600, c['name']))
        if ttl_hours:
            min_ttl, min_name = min(ttl_hours, key=lambda x: x[0])
            logger.info(f"  Shortest-lived cookie '{min_name}': {format_duration(min_ttl)} (note: Google auth cookies have multi-year expirations but server-side session ~24h)")

    logger.info(f"Auth refresh successful: Saved {len(cookies)} new cookies")
    return compute_next_refresh(cookies, refresh_min, refresh_max, logger)


def handle_successful_navigation(page: Page, logger, cookie_file_config, shutdown_event=None,
                                 context=None, cookie_manager=None, cookie_source=None, expected_url=None):
    logger.info("Successfully reached the target page")
    page.click('body')

    handle_popup_dialog(page, logger=logger)

    try:
        from datetime import datetime
        screenshot_dir = logs_dir()
        ensure_dir(screenshot_dir)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        screenshot_path = os.path.join(screenshot_dir, f"SUCCESS_{cookie_file_config}_{timestamp}.png")
        page.screenshot(path=screenshot_path)
        logger.info(f"Saved login success screenshot: {screenshot_path}")
    except Exception as e:
        logger.warning(f"Failed to save screenshot: {e}")

    logger.info("Instance will remain running. Clicking the page every 10 seconds to keep it active")
    time.sleep(15)

    current_ws_status = get_ws_status(page, logger)
    logger.info(f"Initial WS status: {current_ws_status}")

    ever_been_connected = (current_ws_status == "CONNECTED")

    # --- Initialize refresh scheduling ---
    refresh_min = os.getenv("REFRESH_INTERVAL_MIN", "6")
    refresh_max = os.getenv("REFRESH_INTERVAL_MAX", "10")

    try:
        initial_cookies = context.cookies()
        next_refresh = compute_next_refresh(initial_cookies, refresh_min, refresh_max, logger)
    except Exception as e:
        logger.warning(f"Could not compute initial refresh time from cookies (expected if context is fresh): {e}")
        from utils.common import get_next_refresh_time
        next_refresh = get_next_refresh_time(refresh_min, refresh_max)
    logger.info(f"Initial refresh scheduled for: {format_time(next_refresh)}")

    while True:
        if shutdown_event and shutdown_event.is_set():
            logger.info("Shutdown signal received, gracefully exiting keep-alive loop...")
            return

        try:
            dismiss_interaction_modal(page, logger)

            try:
                paused = page.locator('button:visible:has-text("Reload")').first
                if paused.count() > 0:
                    logger.warning("App paused screen detected, clicking 'Reload' to restore...")
                    paused.click(timeout=5000)
                    time.sleep(5)
                    handle_popup_dialog(page, logger=logger)
                    ever_been_connected = False
            except:
                pass

            click_in_iframe(page, logger)

            current_ws_status = get_ws_status(page, logger)
            if current_ws_status == "CONNECTED":
                if not ever_been_connected:
                    logger.info("WS endpoint is reachable")
                    ever_been_connected = True
            elif ever_been_connected:
                logger.info(f"WS endpoint unreachable (status: {current_ws_status}), webapp will auto-reconnect when tunnel is available")
                ever_been_connected = False

            # --- Check for manual force-refresh trigger file ---
            try:
                label = cookie_source.display_name if cookie_source else None
                triggers = ["/tmp/force_refresh"]
                if label:
                    triggers.append(f"/tmp/force_refresh_{label}")
                for fp in triggers:
                    if os.path.exists(fp):
                        os.unlink(fp)
                        logger.warning(f"Manual refresh triggered via {os.path.basename(fp)}")
                        next_refresh = datetime.now(timezone.utc)
            except:
                pass

            # --- Check for scheduled auth refresh ---
            if datetime.now(timezone.utc) >= next_refresh:
                logger.info("Scheduled refresh time reached. Checking page state...")
                try:
                    next_refresh = _do_scheduled_refresh(
                        page, context, cookie_manager, cookie_source, logger, expected_url,
                        refresh_min, refresh_max
                    )
                except Exception as e:
                    if "Target closed" in str(e) or "context or browser has been closed" in str(e):
                        logger.info("Browser target closed during refresh. Exiting keep-alive loop.")
                        return
                    logger.error(f"Error during scheduled auth refresh: {e}")
                    next_refresh = datetime.now(timezone.utc) + timedelta(minutes=5)
                logger.info(f"Next refresh scheduled for: {format_time(next_refresh)}")

            for _ in range(10):
                if shutdown_event and shutdown_event.is_set():
                    logger.info("Shutdown signal received, gracefully exiting keep-alive loop...")
                    return
                time.sleep(1)

        except Exception as e:
            logger.error(f"Error in keep-alive loop: {e}")
            try:
                screenshot_dir = logs_dir()
                ensure_dir(screenshot_dir)
                screenshot_filename = os.path.join(screenshot_dir, f"FAIL_keep_alive_error_{cookie_file_config}.png")
                page.screenshot(path=screenshot_filename, full_page=True)
                logger.info(f"Captured screenshot when error occurred in keep-alive loop: {screenshot_filename}")
            except Exception as screenshot_e:
                logger.error(f"Failed to capture screenshot when error occurred in keep-alive loop: {screenshot_e}")
            raise KeepAliveError(f"Error in keep-alive loop: {e}")
