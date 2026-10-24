
import subprocess


def _osascript(script: str) -> str:
    """Runs one line of AppleScript and returns its output. Raises on failure or after 5 s."""
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=5, check=True)
    return result.stdout.strip()



def set_volume(volume: int) -> dict:
    """Set the system volume on the device.
    Args:
      volume: The volume level to set (0-100)
    """
    try:
        volume = max(0, min(100, int(volume)))  # int() also guarantees only a number reaches the script
        _osascript(f"set volume output volume {volume}" + (" without output muted" if volume > 0 else ""))  # unmute too, or "volume to 50" stays silent
        return {"status": "success", "message": f"System volume set to {volume}%."}
    except Exception as e:
        return {"status": "error", "message": f"Failed to set system volume: {e}"}



def get_volume() -> dict:
    """Get the current system volume on the device."""
    try:
        output = _osascript("output volume of (get volume settings)")
        if output == "missing value":  # devices that handle their own volume (some HDMI / USB DACs) don't report one
            return {"status": "error", "message": "The current output device doesn't report a volume."}
        return {"status": "success", "volume": int(output), "message": f"Current system volume is {output}%."}
    except Exception as e:
        return {"status": "error", "message": f"Failed to get system volume: {e}"}



TOOLS = [set_volume, get_volume]
