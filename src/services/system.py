
# Stubs until Phase 1 step 5 reimplements these for macOS (osascript). They stay registered so the
# LLM's tool list doesn't change; returning an error makes JARVIS tell the user instead of faking success.

def set_volume(volume: int) -> dict:
    """Set the system volume on the PC.
    Args:
      volume: The volume level to set (0-100)
    """
    return {"status": "error", "message": "Setting the system volume isn't supported on this Mac yet."}



def get_volume() -> dict:
    """Get the current system volume on the PC."""
    return {"status": "error", "message": "Reading the system volume isn't supported on this Mac yet."}



TOOLS = [set_volume, get_volume]
