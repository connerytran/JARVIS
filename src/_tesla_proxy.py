import logging
import subprocess
import time
from pathlib import Path

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)  # self-signed, localhost-only

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent
PROXY_EXE = _REPO_ROOT / "bin" / "tesla-http-proxy.exe"
PRIVATE_KEY = _REPO_ROOT / "keys" / "private-key.pem"
TLS_CERT = _REPO_ROOT / "keys" / "proxy-tls.crt"
TLS_KEY = _REPO_ROOT / "keys" / "proxy-tls.key"
PROXY_PORT = 4443
PROXY_BASE = f"https://localhost:{PROXY_PORT}"


def start_proxy(startup_timeout_s: float = 10.0):
    """Launches the Tesla vehicle-command signing proxy as a background process.
    Returns the Popen handle (pass it to stop_proxy on shutdown), or None if it
    couldn't be started -- Tesla tools just won't work in that case, everything
    else in JARVIS still runs normally.
    """
    missing = [p for p in (PROXY_EXE, PRIVATE_KEY, TLS_CERT, TLS_KEY) if not p.exists()]
    if missing:
        logger.warning(f"Tesla proxy not started, missing file(s): {[str(p) for p in missing]}")
        return None

    proc = subprocess.Popen([
        str(PROXY_EXE),
        "-tls-key", str(TLS_KEY),
        "-cert", str(TLS_CERT),
        "-key-file", str(PRIVATE_KEY),
        "-port", str(PROXY_PORT),
    ])

    deadline = time.time() + startup_timeout_s
    while time.time() < deadline:
        if proc.poll() is not None:
            logger.warning(f"Tesla proxy exited immediately (code {proc.returncode}) -- Tesla tools will not work.")
            return None
        try:
            requests.get(PROXY_BASE, verify=False, timeout=1)
            logger.info("Tesla proxy is up.")
            return proc
        except requests.exceptions.RequestException:
            time.sleep(0.5)

    logger.warning("Tesla proxy did not respond in time -- Tesla tools may not work yet.")
    return proc


def stop_proxy(proc):
    if proc is None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    logger.info("Tesla proxy stopped.")
