import os
import threading
import multiprocessing
import signal
import sys
import time

# Load .env file (only in non-Docker environment and if file exists)
def load_env_file():
    """Load .env file, without affecting existing environment variables"""
    if os.environ.get("DOCKER_ENV") or os.path.exists("/.dockerenv"):
        return  # Docker environment, skip loading
    try:
        from dotenv import load_dotenv
        env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
        if os.path.exists(env_path):
            load_dotenv(env_path, override=False)  # override=False does not overwrite existing environment variables
    except ImportError:
        pass  # python-dotenv not installed, skip

load_env_file()

from browser.instance import run_browser_instance
from utils.logger import setup_logging
from utils.paths import cookies_dir, logs_dir
from utils.cookie_manager import CookieManager
from utils.common import clean_env_value, ensure_dir

# Global variables
app_running = False
flask_app = None
# Use multiprocessing.Event for cross-process communication
shutdown_event = multiprocessing.Event()


class ProcessManager:
    """Process manager, responsible for tracking and managing browser processes"""

    def __init__(self):
        self.processes = {}  # {process_id: process_info}
        self.lock = threading.RLock()
        ensure_dir(logs_dir())
        self.logger = setup_logging(str(logs_dir() / 'app.log'), prefix="manager")

    def add_process(self, process, config=None):
        """Add process to manager"""
        with self.lock:
            pid = process.pid if process and hasattr(process, 'pid') else None

            # Allow adding processes with None PID (might still be starting), but log it
            if pid is None:
                # Use temporary ID as key, update after obtaining real PID
                temp_id = f"temp_{len(self.processes)}"
                self.logger.warning(f"Process PID is temporarily None, using temp ID {temp_id}")
            else:
                temp_id = pid

            process_info = {
                'process': process,
                'config': config,
                'pid': pid,
                'is_alive': True,
                'start_time': time.time()
            }
            self.processes[temp_id] = process_info

    def update_temp_pids(self):
        """Update temporary PIDs to real PIDs"""
        with self.lock:
            temp_ids = [k for k in self.processes.keys() if isinstance(k, str) and k.startswith("temp_")]
            for temp_id in temp_ids:
                process_info = self.processes[temp_id]
                process = process_info['process']

                if process and hasattr(process, 'pid') and process.pid is not None:
                    # Update to real PID
                    self.processes[process.pid] = process_info
                    del self.processes[temp_id]
                    process_info['pid'] = process.pid

    def remove_process(self, pid):
        """Remove process from manager"""
        with self.lock:
            if pid in self.processes:
                del self.processes[pid]

    def get_alive_processes(self):
        """Get all alive processes"""
        with self.lock:
            # First attempt to update temporary PIDs
            self.update_temp_pids()

            alive = []
            dead_pids = []

            for pid, info in self.processes.items():
                process = info['process']
                try:
                    # Check if process actually exists and is a child process
                    if process and hasattr(process, 'is_alive') and process.is_alive():
                        alive.append(process)
                    else:
                        dead_pids.append(pid)
                except (ValueError, ProcessLookupError) as e:
                    # Process no longer exists
                    dead_pids.append(pid)
                    self.logger.warning(f"Error checking process {pid}: {e}")

            # Clean dead process records
            for pid in dead_pids:
                self.remove_process(pid)

            return alive

    def terminate_all(self, timeout=10):
        """Gracefully terminate all processes"""
        with self.lock:
            # logger = setup_logging(str(logs_dir() / 'app.log'), prefix="signal")
            # Directly use self.logger, avoid repeating setup_logging

            # First update temporary PIDs
            self.update_temp_pids()

            if not self.processes:
                self.logger.info("No active processes to close")
                return

            self.logger.info(f"Starting to close {len(self.processes)} processes...")

            # Phase 1: Send SIGTERM signal
            active_pids = []
            for pid, info in list(self.processes.items()):
                process = info['process']
                try:
                    # Check if process object is valid and process is alive
                    if process and hasattr(process, 'is_alive') and process.is_alive() and pid is not None:
                        self.logger.info(f"Sending SIGTERM to process {pid} (run time: {time.time() - info['start_time']:.1f}s)")
                        process.terminate()
                        active_pids.append(pid)
                    else:
                        self.logger.info(f"Process {pid if pid is not None else 'None'} has stopped or is invalid")
                except (ValueError, ProcessLookupError, AttributeError) as e:
                    self.logger.warning(f"Error accessing process {pid if pid is not None else 'None'}: {e}")

            if not active_pids:
                self.logger.info("All processes have stopped")
                return

            # Phase 2: Wait for processes to exit
            self.logger.info(f"Waiting for {len(active_pids)} processes to exit gracefully...")
            start_wait = time.time()
            while time.time() - start_wait < 5:  # Wait max 5 seconds
                still_alive = []
                for pid in active_pids:
                    if pid in self.processes:
                        process = self.processes[pid]['process']
                        try:
                            if process and hasattr(process, 'is_alive') and process.is_alive():
                                still_alive.append(pid)
                        except (ValueError, ProcessLookupError, AttributeError):
                                pass
                if not still_alive:
                    self.logger.info("All processes have exited gracefully")
                    return
                time.sleep(0.5)
            
            self.logger.info(f"{len(still_alive)} processes are still running, preparing to force close...")

            # Phase 3: Force kill remaining running processes
            for pid in active_pids:
                if pid in self.processes and pid is not None:
                    process = self.processes[pid]['process']
                    try:
                        if process and hasattr(process, 'is_alive') and process.is_alive():
                            self.logger.warning(f"Process {pid} did not respond to SIGTERM, force terminating")
                            process.kill()
                    except (ValueError, ProcessLookupError, AttributeError) as e:
                        self.logger.info(f"Process {pid} terminated: {e}")

            self.logger.info("All processes closed")

    def get_count(self):
        """Get total number of managed processes"""
        with self.lock:
            return len(self.processes)

    def get_alive_count(self):
        """Get number of alive processes"""
        return len(self.get_alive_processes())


# Global process manager
process_manager = ProcessManager()


def load_instance_configurations(logger):
    """
    Use CookieManager to parse environment variables and Cookies directory, creating separate browser instance configurations for each Cookie source.
    """
    # 1. Read shared URL for all instances
    shared_url = clean_env_value(os.getenv("CAMOUFOX_INSTANCE_URL"))
    if not shared_url:
        logger.error("Error: Missing environment variable CAMOUFOX_INSTANCE_URL. All instances require a shared target URL")
        return None, None

    # 2. Read global settings
    global_settings = {
        "headless": clean_env_value(os.getenv("CAMOUFOX_HEADLESS")) or "virtual",
        "url": shared_url  # All instances use this URL
    }

    proxy_value = clean_env_value(os.getenv("CAMOUFOX_PROXY"))
    if proxy_value:
        global_settings["proxy"] = proxy_value

    # 3. Use CookieManager to detect all Cookie sources
    cookie_manager = CookieManager(logger)
    sources = cookie_manager.detect_all_sources()

    # Check if any Cookie sources exist
    if not sources:
        logger.error("Error: No Cookie sources found (neither JSON files nor environment variable Cookies)")
        return None, None

    # 4. Create instance configurations for each Cookie source
    instances = []
    for source in sources:
        if source.type == "file":
            instances.append({
                "cookie_file": source.identifier,
                "cookie_source": source
            })
        elif source.type == "env_var":
            # Extract index from environment variable name, e.g., "USER_COOKIE_1" -> 1
            env_index = source.identifier.split("_")[-1]
            instances.append({
                "cookie_file": None,
                "env_cookie_index": int(env_index),
                "cookie_source": source
            })

    logger.info(f"Will start {len(instances)} browser instances")

    return global_settings, instances

def start_browser_instances(run_mode="standalone"):
    """Core logic to start browser instances"""
    global app_running, process_manager, shutdown_event

    log_dir = logs_dir()
    logger = setup_logging(str(log_dir / 'app.log'))
    logger.info("---------------------Camoufox instance manager starting---------------------")
    start_delay = int(os.getenv("INSTANCE_START_DELAY", "30"))
    logger.info(f"Run mode: {run_mode}; Instance start interval: {start_delay} seconds")

    global_settings, instance_profiles = load_instance_configurations(logger)
    if not instance_profiles:
        logger.error("Error: No instance configurations found in environment variables")
        return

    for i, profile in enumerate(instance_profiles, 1):
        if not app_running:
            break

        final_config = global_settings.copy()
        final_config.update(profile)

        if 'url' not in final_config:
            logger.warning(f"Warning: Skipping invalid configuration item (missing url): {profile}")
            continue

        cookie_source = final_config.get('cookie_source')

        if cookie_source:
            if cookie_source.type == "file":
                logger.info(
                    f"Starting {i}/{len(instance_profiles)} browser instance (file: {cookie_source.display_name})..."
                )
            elif cookie_source.type == "env_var":
                logger.info(
                    f"Starting {i}/{len(instance_profiles)} browser instance (env: {cookie_source.display_name})..."
                )
        else:
            logger.error(f"Error: cookie_source object missing in configuration")
            continue

        # Pass shutdown_event to sub-process
        process = multiprocessing.Process(target=run_browser_instance, args=(final_config, shutdown_event))
        process.start()
        # Wait a short time for process to get PID, then add to manager
        time.sleep(0.1)
        process_manager.add_process(process, final_config)

        # Wait for configured time, to avoid high CPU usage due to concurrent startup
        # Even for the last instance, wait for some time for initialization before entering main loop
        time.sleep(start_delay)

    # Wait for all processes
    previous_count = None
    last_log_time = 0
    try:
        while app_running:
            alive_processes = process_manager.get_alive_processes()
            current_count = len(alive_processes)

            # Log only when count changes or after a certain interval, to avoid too frequent logs
            now = time.time()
            if current_count != previous_count or now - last_log_time >= 600:
                logger.info(f"Current running browser instances: {current_count}")
                previous_count = current_count
                last_log_time = now

            if not alive_processes:
                logger.info("All browser processes have finished, main process exiting")
                break

            # Wait for processes and clean dead processes
            for process in alive_processes:
                try:
                    process.join(timeout=1)
                except:
                    pass

            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt captured, waiting for signal handler to complete shutdown...")
        # Don't close processes here, let signal handler handle it uniformly
        pass

    # Ensure exit after all processes end
    logger.info("Browser instance manager run finished")

def run_standalone_mode():
    """Standalone mode"""
    global app_running
    app_running = True

    start_browser_instances(run_mode="standalone")

def run_server_mode():
    """Server mode"""
    global app_running, flask_app

    log_dir = logs_dir()
    server_logger = setup_logging(str(log_dir / 'app.log'), prefix="server")

    # Dynamically import Flask (only when needed)
    try:
        from flask import Flask, jsonify
        flask_app = Flask(__name__)
    except ImportError:
        server_logger.error("Error: Server mode requires Flask, please install: pip install flask")
        return

    app_running = True

    # Start browser instances in background thread
    browser_thread = threading.Thread(target=lambda: start_browser_instances(run_mode="server"), daemon=True)
    browser_thread.start()

    # Define routes
    @flask_app.route('/health')
    def health_check():
        """Health check endpoint"""
        global process_manager
        running_count = process_manager.get_alive_count()
        total_count = process_manager.get_count()
        return jsonify({
            'status': 'healthy',
            'browser_instances': total_count,
            'running_instances': running_count,
            'message': f'Application is running with {running_count} active browser instances'
        })

    @flask_app.route('/')
    def index():
        """Main page endpoint"""
        global process_manager
        running_count = process_manager.get_alive_count()
        total_count = process_manager.get_count()
        return jsonify({
            'status': 'running',
            'browser_instances': total_count,
            'running_instances': running_count,
            'run_mode': 'server',
            'message': 'Camoufox Browser Automation is running in server mode'
        })

    # Disable Flask's default logs
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)

    # Start Flask server
    try:
        flask_app.run(host='0.0.0.0', port=7860, debug=False)
    except KeyboardInterrupt:
        server_logger.info("Server is shutting down...")

def signal_handler(signum, frame):
    """Unified signal handler - only main process should execute this logic"""
    global app_running, process_manager, shutdown_event

    # Immediately set logger to ensure后续 info is visible
    logger = setup_logging(str(logs_dir() / 'app.log'), prefix="signal")
    logger.info(f"Signal {signum} received, starting processing...")

    # Check if it is the main process, prevent child process from executing shutdown logic
    current_pid = os.getpid()

    # Use a simple method to judge: if child process, usually does not have control of global variable process_manager
    # Or by judging multiprocessing.current_process().name
    if multiprocessing.current_process().name != 'MainProcess':
         # Child process received signal, usually should be managed by main process, 
         # or child process will be terminated due to SIGTERM sent by main process
         # Here we choose to ignore, let main process manage via terminate, 
         # or child process exit via shutdown_event
         logger.info(f"Child process {current_pid} received signal {signum}, ignoring main process signal handling logic")
         return

    logger.info(f"Main process {current_pid} received signal {signum}, shutting down application...")

    # 1. Immediately set global flag to prevent new process creation
    app_running = False

    # 2. Set cross-process shutdown event to notify all child processes to exit gracefully
    try:
        shutdown_event.set()
        logger.info("Global shutdown event set (shutdown_event)")
    except Exception as e:
        logger.error(f"Error setting shutdown event: {e}")

    # 3. Call graceful termination method of process manager
    try:
        process_manager.terminate_all(timeout=10)
    except Exception as e:
        logger.error(f"Error calling terminate_all: {e}")

    logger.info("Application shutdown process complete, main process exiting")
    sys.exit(0)

def main():
    """Main entry function"""
    # Initialize necessary directories
    ensure_dir(logs_dir())
    ensure_dir(cookies_dir())

    # Register signal handler - add capture for more signals
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    # Some environments might have other signals
    try:
        signal.signal(signal.SIGQUIT, signal_handler)
    except (ValueError, AttributeError):
        pass
    try:
        signal.signal(signal.SIGHUP, signal_handler)
    except (ValueError, AttributeError):
        pass

    # Check run mode environment variable
    hg_mode = os.getenv('HG', '').lower()

    if hg_mode == 'true':
        run_server_mode()
    else:
        run_standalone_mode()

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
