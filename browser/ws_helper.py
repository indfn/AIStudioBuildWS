import time
import random
from playwright.sync_api import Page, FrameLocator


def get_preview_frame(page: Page, logger=None) -> FrameLocator:
    """
    Get the FrameLocator for the preview iframe.
    """
    try:
        # Find the iframe with title "Preview"
        frame = page.frame_locator('iframe[title="Preview"]')
        return frame
    except Exception as e:
        if logger:
            logger.warning(f"Failed to get Preview iframe: {e}")
        return None


def get_ws_status(page: Page, logger=None) -> str:
    """
    Get WS connection status in the page (inside iframe).
    Returns: CONNECTED, IDLE, CONNECTING, or UNKNOWN
    """
    try:
        frame = get_preview_frame(page, logger)
        if not frame:
            return "UNKNOWN"
        
        # Search for status text element containing "WS:" inside iframe
        # Based on screenshots, status is displayed in format like "WS: CONNECTED"
        status_element = frame.locator('text=/WS:\\s*(CONNECTED|IDLE|CONNECTING)/i').first
        if status_element.is_visible(timeout=3000):
            text = status_element.text_content()
            if text:
                if "CONNECTED" in text.upper():
                    return "CONNECTED"
                elif "IDLE" in text.upper():
                    return "IDLE"
                elif "CONNECTING" in text.upper():
                    return "CONNECTING"
        return "UNKNOWN"
    except Exception as e:
        if logger:
            logger.warning(f"Error getting WS status: {e}")
        return "UNKNOWN"


def click_disconnect(page: Page, logger=None) -> bool:
    """
    Click Disconnect button to disconnect WS (inside iframe).
    """
    try:
        frame = get_preview_frame(page, logger)
        if not frame:
            return False
        
        disconnect_btn = frame.locator('button:has-text("Disconnect")')
        if disconnect_btn.count() > 0 and disconnect_btn.first.is_visible(timeout=3000):
            disconnect_btn.first.click(timeout=5000)
            if logger:
                logger.info("Clicked Disconnect button")
            time.sleep(1)
            return True
        if logger:
            logger.warning("Visible Disconnect button not found")
        return False
    except Exception as e:
        if logger:
            logger.warning(f"Failed to click Disconnect button: {e}")
        return False


def click_connect(page: Page, logger=None) -> bool:
    """
    Click Connect button to establish WS connection (inside iframe).
    """
    try:
        frame = get_preview_frame(page, logger)
        if not frame:
            return False
        
        connect_btn = frame.locator('button:has-text("Connect")')
        if connect_btn.count() > 0 and connect_btn.first.is_visible(timeout=3000):
            connect_btn.first.click(timeout=5000)
            if logger:
                logger.info("Clicked Connect button")
            time.sleep(1)
            return True
        if logger:
            logger.warning("Visible Connect button not found")
        return False
    except Exception as e:
        if logger:
            logger.warning(f"Failed to click Connect button: {e}")
        return False


def wait_for_ws_connected(page: Page, logger=None, timeout: int = 30) -> bool:
    """
    Wait for WS status to become CONNECTED.
    """
    start_time = time.time()
    while time.time() - start_time < timeout:
        status = get_ws_status(page, logger)
        if status == "CONNECTED":
            return True
        time.sleep(1)
    return False


def reconnect_ws(page: Page, logger=None) -> str:
    """
    Perform disconnect and reconnect process, return final WS status.
    Flow: Close overlay -> Disconnect -> Wait for IDLE -> Connect -> Wait for CONNECTED -> Get status
    """
    if logger:
        logger.info("Starting WS reconnection process: Disconnect -> Connect")
    
    # Close interaction-modal overlay first (if exists)
    dismiss_interaction_modal(page, logger)
    
    # Disconnect first
    click_disconnect(page, logger)
    time.sleep(2)
    
    # Check if becomes IDLE
    status = get_ws_status(page, logger)
    if logger:
        logger.info(f"WS status after disconnect: {status}")
    
    # Reconnect
    click_connect(page, logger)
    time.sleep(2)
    
    # Wait for connection success
    if wait_for_ws_connected(page, logger, timeout=15):
        status = get_ws_status(page, logger)
        if logger:
            logger.info(f"WS status after reconnection: {status}")
        return status
    else:
        status = get_ws_status(page, logger)
        if logger:
            logger.warning(f"WS reconnection timed out, current status: {status}")
        return status


def dismiss_interaction_modal(page: Page, logger=None) -> bool:
    """
    Detect and close interaction-modal or cdk-overlay-backdrop.
    Trigger overlay closure by simulating mouse movement or clicking the backdrop.
    
    Returns: True if successful, False if not found or failed
    """
    try:
        # Check for multiple types of overlays
        modal = page.locator('div.interaction-modal, div.cdk-overlay-backdrop')
        if modal.count() == 0 or not modal.first.is_visible(timeout=500):
            return False
        
        if logger:
            logger.info("Overlay detected (modal or backdrop), attempting to close...")
        
        # Strategy 1: Mouse movement in iframe (works for interaction-modal)
        iframe = page.locator('iframe[title="Preview"]')
        if iframe.count() > 0:
            iframe_box = iframe.first.bounding_box()
            if iframe_box:
                curr_x = iframe_box['x'] + random.randint(50, int(iframe_box['width']) - 50)
                curr_y = iframe_box['y'] + random.randint(50, int(iframe_box['height']) - 50)
                
                for i in range(20):
                    delta_x = random.randint(-30, 30)
                    delta_y = random.randint(-20, 20)
                    curr_x = max(iframe_box['x'] + 20, min(iframe_box['x'] + iframe_box['width'] - 20, curr_x + delta_x))
                    curr_y = max(iframe_box['y'] + 20, min(iframe_box['y'] + iframe_box['height'] - 20, curr_y + delta_y))
                    page.mouse.move(curr_x, curr_y)
                    time.sleep(0.05)
                    
                    if modal.count() == 0 or not modal.first.is_visible(timeout=100):
                        if logger:
                            logger.info("Successfully closed overlay via movement")
                        return True

        # Strategy 2: If still visible, try clicking the backdrop itself to dismiss (common for cdk-overlays)
        if modal.first.is_visible(timeout=500):
            modal.first.click(timeout=2000)
            if logger:
                logger.info("Successfully closed overlay via backdrop click")
            return True
        
        return False
    except Exception as e:
        if logger:
            logger.debug(f"Error closing interaction-modal/backdrop: {e}")
        return False

        
        if logger:
            logger.info("Interaction-modal detected, attempting to close...")
        
        iframe = page.locator('iframe[title="Preview"]')
        if iframe.count() > 0:
            iframe_box = iframe.first.bounding_box()
            if iframe_box:
                # Random start position
                curr_x = iframe_box['x'] + random.randint(50, int(iframe_box['width']) - 50)
                curr_y = iframe_box['y'] + random.randint(50, int(iframe_box['height']) - 50)
                
                # Continuously move until overlay closed, max 30 attempts
                for i in range(30):
                    # Move randomly from current position
                    delta_x = random.randint(-30, 30)
                    delta_y = random.randint(-20, 20)
                    curr_x = max(iframe_box['x'] + 20, min(iframe_box['x'] + iframe_box['width'] - 20, curr_x + delta_x))
                    curr_y = max(iframe_box['y'] + 20, min(iframe_box['y'] + iframe_box['height'] - 20, curr_y + delta_y))
                    
                    page.mouse.move(curr_x, curr_y)
                    time.sleep(0.05)
                    
                    # Check if overlay is closed after each movement
                    if modal.count() == 0 or not modal.first.is_visible(timeout=100):
                        if logger:
                            logger.info("Successfully closed interaction-modal overlay")
                        return True
        
        return False
    except Exception as e:
        if logger:
            logger.debug(f"Error closing interaction-modal: {e}")
        return False


def click_in_iframe(page: Page, logger=None) -> bool:
    """
    Randomly move mouse and click inside iframe, used for keep-alive.
    Avoid top (status bar/buttons) and right areas.
    
    Returns: True if successful, False if failed
    """
    try:
        iframe = page.locator('iframe[title="Preview"]')
        if iframe.count() == 0:
            return False
        
        iframe_box = iframe.first.bounding_box()
        if not iframe_box:
            return False
        
        # Safe area: Avoid top 80 pixels and right 200 pixels
        safe_left = iframe_box['x'] + 50
        safe_right = iframe_box['x'] + iframe_box['width'] - 200
        safe_top = iframe_box['y'] + 80
        safe_bottom = iframe_box['y'] + iframe_box['height'] - 50
        
        # Ensure safe area is valid
        if safe_right <= safe_left or safe_bottom <= safe_top:
            return False
        
        # Random start point (within safe area)
        curr_x = random.randint(int(safe_left), int(safe_right))
        curr_y = random.randint(int(safe_top), int(safe_bottom))
        
        # Move randomly for a few steps (keep within safe area)
        for _ in range(random.randint(3, 6)):
            delta_x = random.randint(-30, 30)
            delta_y = random.randint(-20, 20)
            curr_x = max(int(safe_left), min(int(safe_right), curr_x + delta_x))
            curr_y = max(int(safe_top), min(int(safe_bottom), curr_y + delta_y))
            page.mouse.move(curr_x, curr_y)
            time.sleep(0.05)
        
        # Click current position
        page.mouse.click(curr_x, curr_y)
        return True
    except Exception as e:
        if logger:
            logger.debug(f"Failed to click inside iframe: {e}")
        return False
