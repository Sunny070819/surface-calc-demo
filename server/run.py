"""Packaged-exe entry point (PyInstaller --onefile target).

Starts the same Flask app as app.py's own __main__, but additionally opens
the customer's default browser once the server is actually listening --
a double-clicked exe has no terminal for anyone to read "server started"
from, so the browser opening is the only feedback most people will get.

Also handles the "customer double-clicks the exe a second time while it's
already running" case: rather than crashing with a raw socket error, it just
opens a browser tab to the already-running instance and exits.
"""

import socket
import threading
import time
import urllib.request
import webbrowser

import app as app_module
import config

HOST = "127.0.0.1"
PORT = 5000
URL = f"http://{HOST}:{PORT}/"


def _port_already_in_use():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((HOST, PORT)) == 0


def _open_browser_when_ready(timeout_seconds=20):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(URL, timeout=1)
            break
        except Exception:
            time.sleep(0.3)
    webbrowser.open(URL)


def main():
    print("台芯實業 邊角料管理系統")
    print(f"資料/設定檔位置：{config.EXTERNAL_DIR}")
    print(f"SAP 連線：{'已設定' if config.SAP_ICF_URL else '尚未設定（sap_config.json 不存在或不完整）'}")

    if _port_already_in_use():
        print(f"偵測到 {URL} 已經在執行中，直接開啟瀏覽器分頁。")
        webbrowser.open(URL)
        return

    threading.Thread(target=_open_browser_when_ready, daemon=True).start()
    print(f"伺服器啟動中，稍後會自動開啟瀏覽器（{URL}）。關閉這個視窗即可停止程式。")
    app_module.app.run(host="0.0.0.0", port=PORT, debug=False)


if __name__ == "__main__":
    main()
