import time
import os
import random
from playwright.sync_api import Page, expect
from utils.paths import logs_dir
from utils.common import ensure_dir
from browser.ws_helper import reconnect_ws, get_ws_status, dismiss_interaction_modal, click_in_iframe

class KeepAliveError(Exception):
    pass

def handle_popup_dialog(page: Page, logger=None):
    """
    检查并处理弹窗。
    遍历多种关闭按钮、iframe内按钮和关闭图标直到没有弹窗。
    """
    logger.info("Starting popup processing...")
    
    button_names = ["Got it", "Continue to the app", "Skip", "Dismiss"]
    max_iterations = 10
    total_clicks = 0
    
    try:
        for iteration in range(max_iterations):
            clicked_in_round = False
            time.sleep(1)
            
            # Try clicking buttons on the main page
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
            
            # Try clicking buttons inside the Preview iframe
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
            
            # Try aria-label close buttons
            try:
                close_btn = page.locator('[aria-label="Close"]').first
                if close_btn.count() > 0 and close_btn.is_visible(timeout=300):
                    close_btn.click(timeout=2000)
                    total_clicks += 1
                    clicked_in_round = True
                    time.sleep(1)
            except:
                pass
            
            # Press Escape as fallback
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

def handle_successful_navigation(page: Page, logger, cookie_file_config, shutdown_event=None, cookie_validator=None):
    """
    在成功导航到目标页面后，执行后续操作（处理弹窗、保持运行）。
    """
    logger.info("Successfully reached the target page")
    page.click('body') # Give focus to the page

    # Check and handle popups
    handle_popup_dialog(page, logger=logger)

    # Save screenshot of successful login
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

    if cookie_validator:
        logger.info("Cookie validator created, will periodically verify Cookie validity")

    logger.info("Instance will remain running. Clicking the page every 10 seconds to keep it active")

    # Wait for page loading and rendering
    time.sleep(15)

    # Record initial WS status
    last_ws_status = get_ws_status(page, logger)
    logger.info(f"Initial WS status: {last_ws_status}")

    # Add Cookie validation counter
    click_counter = 0

    # Initialize anti-bot refresh timer
    next_heartbeat_time = time.time() + random.randint(50 * 60, 80 * 60) # 50-80 minutes

    while True:
        # Check if shutdown signal received
        if shutdown_event and shutdown_event.is_set():
            logger.info("Shutdown signal received, gracefully exiting keep-alive loop...")
            return

        try:
            # Detect and close interaction-modal overlay (if it appears)
            dismiss_interaction_modal(page, logger)

            # Randomly move and click in iframe to keep alive
            click_in_iframe(page, logger)
            click_counter += 1

            # Check if WS status has changed
            current_ws_status = get_ws_status(page, logger)
            if current_ws_status != last_ws_status:
                logger.warning(f"WS status change: {last_ws_status} -> {current_ws_status}")
                
                # If not CONNECTED status, attempt reconnect
                if current_ws_status != "CONNECTED":
                    logger.info("WS disconnected, attempting to reconnect...")
                    reconnect_ws(page, logger)
                    current_ws_status = get_ws_status(page, logger)
                    logger.info(f"WS status after reconnection: {current_ws_status}")
                
                last_ws_status = current_ws_status

            # Perform full Cookie validation every 360 clicks (1 hour)
            if cookie_validator and click_counter >= 360:  # 360 * 10 seconds = 3600 seconds = 1 hour
                is_valid = cookie_validator.validate_cookies_in_main_thread()

                if not is_valid:
                    cookie_validator.shutdown_instance_on_cookie_failure()
                    return

                click_counter = 0  # Reset counter

            # Probabilistic anti-bot heartbeat reload
            if time.time() > next_heartbeat_time:
                logger.info("Triggered probabilistic heartbeat reload")
                page.reload(wait_until='networkidle')
                time.sleep(5)
                handle_popup_dialog(page, logger=logger)
                next_heartbeat_time = time.time() + random.randint(50 * 60, 80 * 60)
                logger.info(f"Heartbeat reload complete. Next reload at {time.ctime(next_heartbeat_time)}")

            # Use interruptible sleep, checking shutdown signal every second
            for _ in range(10):  # 10 seconds = 10 checks of 1 second
                if shutdown_event and shutdown_event.is_set():
                    logger.info("Shutdown signal received, gracefully exiting keep-alive loop...")
                    return
                time.sleep(1)

        except Exception as e:
            logger.error(f"Error in keep-alive loop: {e}")
            # Capture screenshot when error occurs in keep-alive loop
            try:
                screenshot_dir = logs_dir()
                ensure_dir(screenshot_dir)
                screenshot_filename = os.path.join(screenshot_dir, f"FAIL_keep_alive_error_{cookie_file_config}.png")
                page.screenshot(path=screenshot_filename, full_page=True)
                logger.info(f"Captured screenshot when error occurred in keep-alive loop: {screenshot_filename}")
            except Exception as screenshot_e:
                logger.error(f"Failed to capture screenshot when error occurred in keep-alive loop: {screenshot_e}")
            raise KeepAliveError(f"Error in keep-alive loop: {e}")