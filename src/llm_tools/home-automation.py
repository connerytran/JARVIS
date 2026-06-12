from pathlib import Path
from requests import get, post
from dotenv import load_dotenv
import os
import yaml

load_dotenv()
HA_TOKEN = os.getenv("HA_TOKEN")
HEADERS = {"Authorization": f"Bearer {HA_TOKEN}"}

with open(Path(__file__).parent / "_HA-config.yaml", "r") as f:
    HA_CONFIG = yaml.safe_load(f)

AVAILABLE_LIGHTS = list(HA_CONFIG['lights'].keys())
AVAILABLE_COLORS = list(HA_CONFIG['colors'].keys())
AVAILABLE_COLOR_TEMPS = list(HA_CONFIG['color_temps'].keys())



def control_light(device_name: str, brightness: int = None, color: str = None, temp: str = None) -> dict:
    light_state = "off" if brightness == 0 else "on"

    entity_id = HA_CONFIG['lights'].get(device_name)
    color_name = HA_CONFIG['colors'].get(color)
    color_temp = HA_CONFIG['color_temps'].get(temp)
    url = f"http://localhost:8123/api/services/light/turn_on"
    data = {"entity_id": entity_id}
    if color_name:
        data["color_name"] = color_name
    if color_temp is not None:
        data["color_temp_kelvin"] = color_temp
    if brightness is not None:
        data["brightness"] = brightness
    response = post(url, headers=HEADERS, json=data)

    if response.status_code == 200:
        return {"status": "success", "message": f"Turned {light_state} {device_name}."}
    else:
        return {"status": "error", "message": f"Failed to turn {light_state} {device_name}. Response: {response.text}"}



# We need to set the docstring after because f string cant be used in function definition
control_light.__doc__ = f"""Sets a SINGLE light's properties in Home Assistant.
Args:
    device_name: The name of the light device to control. One of: {', '.join(AVAILABLE_LIGHTS)}. If the user asks for a device that is not in this list, return an error message with the available devices. ONLY CHOOSE OPTIONS FROM THIS LIST.
    brightness: The brightness level (0-255) (assume the user means 0-100 and convert to 0-255. set brightness 0 to turn off the light)
    color: The color of the light. Use only for color not temperature. One of: {', '.join(AVAILABLE_COLORS)}
    temp: Use for changing the color temperature. User will say one of these and select one from here: {', '.join(AVAILABLE_COLOR_TEMPS)}
"""



TOOLS = [ control_light ]