
from ctypes import cast, POINTER # python stdlib for interacting with C lvl code and windows APIs
from comtypes import CLSCTX_ALL # COM (component object model) controls windows audio
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

def set_volume(volume: int) -> dict:
    """Set the system volume on the PC.
    Args:
      volume: The volume level to set (0-100)
    """

    try:
        devices = AudioUtilities.GetSpeakers()

        # activates volume control interface on that device using COM interface iid
        interface = devices._dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)

        # Activate returns a generic COM object, so we must cast to IAudioEndpointVolume to access volume control methods
        vol = cast(interface, POINTER(IAudioEndpointVolume))
        vol.SetMasterVolumeLevelScalar(volume / 100, None)
        return {"status": "success", "message": f"System volume set to {volume}%."}
    except Exception as e:
        return {"status": "error", "message": f"Failed to set system volume: {str(e)}"}

TOOLS = [set_volume]