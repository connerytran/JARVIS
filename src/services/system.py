
from ctypes import cast, POINTER # python stdlib for interacting with C lvl code and windows APIs
from comtypes import CLSCTX_ALL # COM (component object model) controls windows audio
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

_speakers = AudioUtilities.GetSpeakers()        # aquires the default audio device (speakers) on the system
_audio_interface = _speakers._dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)  # activates volume control interface on that device using COM interface iid
_volume = cast(_audio_interface, POINTER(IAudioEndpointVolume))                     # Activate returns a generic COM object, so we must cast to IAudioEndpointVolume to access volume control methods

def set_volume(volume: int) -> dict:
    """Set the system volume on the PC.
    Args:
      volume: The volume level to set (0-100)
    """

    try: 
        _volume.SetMasterVolumeLevelScalar(volume / 100, None)
        return {"status": "success", "message": f"System volume set to {volume}%."}
    except Exception as e:
        return {"status": "error", "message": f"Failed to set system volume: {str(e)}"}
    


def get_volume() -> dict:
    """Get the current system volume on the PC."""
    try:
        current_volume = int(_volume.GetMasterVolumeLevelScalar() * 100)
        return {"status": "success", "volume": current_volume, "message": f"Current system volume is {current_volume}%."}
    except Exception as e:
        return {"status": "error", "message": f"Failed to get system volume: {str(e)}"}
    
    

TOOLS = [set_volume, get_volume]