import subprocess


def osascript(script: str, timeout: float = 5) -> str:
    """Runs one line of AppleScript and returns its output.
    Raises RuntimeError with osascript's own message on failure (e.g. -1743, "Not authorized to send
    Apple events", when macOS Automation permission is missing), or TimeoutExpired after `timeout` s.
    """
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"osascript exited with status {result.returncode}")
    return result.stdout.strip()
