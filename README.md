# AIStudioBuildWS - Enhanced Google AI Studio WebSocket Proxy

This is a fork of `hkfires/AIStudioBuildWS` enhanced with **Session Permanence** logic. It enables long-term, low-maintenance deployment on VPS or HuggingFace by automatically rotating session tokens and persisting them to disk.

### Key Fork Enhancements
- **Probabilistic Auth Refresh**: Automatically reloads the AI Studio page at randomized intervals (default 8-11 hours) to rotate session tokens before they expire (preventing the common 16-24h logout).
- **Generation-Aware Scheduling**: Logically detects if a generation is currently active (via `mat-spinner`) and waits for it to finish before triggering a refresh.
- **Persistent Cookie Sync**: Newly acquired session cookies are automatically saved back to the JSON files or environment variables, allowing sessions to persist across Docker restarts or system reboots.
- **Over-the-Air Popup Dismissal**: Automatically detects and dismisses Google "Terms of Service" or "Got it" overlays that frequently block headless automation.
- **Multi-Process Safety**: Thread-safe cookie management ensures that multiple browser instances (accounts) can run concurrently without file corruption.
- **Cookie Expiry Checks**: On startup, inspects every cookie's `expires` field and warns if the shortest-lived cookie expires before the next scheduled refresh (or if it's already expired).
- **Adaptive Refresh Scheduling**: If a cookie expires sooner than the normal refresh window, the system automatically brings the refresh forward to 30 minutes before expiry — no manual intervention needed.
- **Cookie Rotation Audit**: After each refresh, logs exactly which cookies changed value (token rotation) and how much time was added to their expiry, confirming the refresh actually worked.
- **Urgent Retry Safety Net**: If a refresh fails to extend cookie lifetimes, the system retries in 5 minutes instead of sleeping for hours.
---

> **Note:** The deployment scheme in this tutorial requires use with `CLIProxyAPI`. Before starting, ensure you have a running `CLIProxyAPI` instance.

CLIProxyAPI v6.3.x and later supports connecting AI Providers via WebSocket, and was the first to support AIStudio.

However, this method requires a browser to be kept open to run the WebSocket communication program on AIStudioBuild, which is inconvenient. If you choose to deploy it on a VPS, you will face high VPS memory requirements.

To solve this, I spent some time experimenting with various headless browser solutions. Finally, I chose to use Docker to deploy on HuggingFace, which makes full use of HuggingFace's free instance large memory advantage to achieve zero-cost deployment.

### Step 1: Configure AIStudioBuild Application

You need to configure the WebSocket communication program on AIStudioBuild according to your `CLIProxyAPI` settings: Open the [example program](https://aistudio.google.com/apps/drive/1CPW7FpWGsDZzkaYgYOyXQ_6FWgxieLmL) provided officially, copy the program, and **you must** modify the two places indicated by the red box in the image. If `wsauth` is set to `true` in `CLIProxyAPI`, you need to set `JWT_TOKEN` to the `api-keys` value intended for authentication in `CLIProxyAPI`; set `WEBSOCKET_PROXY_URL` to the address where `CLIProxyAPI` is located, for example: `wss://mycap.example.com/v1/ws`. After setting, save it and record the link to this application for later use.

![](https://img.072899.xyz/2025/11/359a2572d0206c20dba7fe12a136d6e8.png)

When using multiple accounts, you need to take one extra step: set the access permission of this application to `Public`.

![](https://img.072899.xyz/2025/11/69c6395d1a98c38c68bc6c8dd46b3014.png)

**Security Warning:** After setting it to `Public`, be sure to keep your link safe. **Do not** share this link publicly to avoid leaking authorization information.

### Step 2: Prepare AIStudio Cookie

Cookies can be obtained in two ways; choose one. It is recommended to use a fingerprint browser to obtain them (USE FIREFOX as browser fingerprint):

Method 1 (Recommended): Use a fingerprint browser like AdsPower/BitBrowser, log in to https://aistudio.google.com/ , log out, edit the browser environment, and copy the Cookie content as shown in the image below:

![](https://img.072899.xyz/2025/11/c60399120703a24bdd450d38e31052a5.png)

Method 2: Use the privacy mode of a normal browser like Chrome, log in to https://aistudio.google.com/ , and copy the Cookie content in the browser's developer tools as shown in the image below:

![](https://img.072899.xyz/2025/11/51f860bf363cab01aa4c3fd5181b7f72.png)

### Step 3 (1): Deploy HuggingFace Space

Open https://huggingface.co/spaces/hkfires/AIStudioBuildWS and duplicate the Space. Fill in the link to the program prepared in the first step at `CAMOUFOX_INSTANCE_URL`, fill in the Cookie prepared in the second step at `USER_COOKIE_1`, and click Duplicate Space.

![](https://img.072899.xyz/2025/11/04e84ce3b0f2abe7ae9e717ac8b5aa0b.png)

Wait for the HuggingFace build to complete. If the following log appears, the deployment is successful:

![](https://img.072899.xyz/2025/11/e818f38cfb272c1fc10ca97c2ef23c6b.png)

If there are multiple accounts, refer to `USER_COOKIE_1` and add environment variables like `USER_COOKIE_2`, `USER_COOKIE_3`, etc., in the settings of the HuggingFace Space.

**Optional Configuration:** If you need to modify the log display time zone, you can add the `TZ_OFFSET` environment variable. For example, setting it to `8` means UTC+8 (Beijing time, default value), and setting it to `0` means UTC.

**Important Reminder:** Cookies are sensitive information. Please **be sure to use "Secrets"** (not "Variables") to store them to prevent Cookie leakage.

### Step 3 (2): Server Docker Deployment

If you have your own server (VPS), you can also use Docker Compose for deployment.

1.  **Download code**
    ```bash
    git clone https://github.com/hkfires/AIStudioBuildWS.git
    cd AIStudioBuildWS
    ```

2.  **Configure environment variables**
    Copy `.env.example` to `.env` and fill in the necessary information (`CAMOUFOX_INSTANCE_URL`, etc.).

    ```bash
    cp .env.example .env
    nano .env
    ```
    (Recommended) You can place Cookie files in JSON format in the `cookies` directory (the filename is arbitrary), and the program will automatically read them.
    
    ```bash
    mkdir cookies
    cd cookies
    nano filename.json
    ```
    
    Or you can also place your cookie token string (if you obtained cookies the other way) in .env as found in the bottom of the file as USER_COOKIE_1="..."
    
3.  **Start the service**
    ```bash
    docker compose up -d --build
    ```

After successful deployment, we should see logs similar to the following in `CLIProxyAPI`. With this, the entire deployment is complete.

![](https://img.072899.xyz/2025/11/e0db39f81a3bbb956cbe9364e656a76f.png)
