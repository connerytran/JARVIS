
from services import TOOLS, TOOL_MAP
from ollama import chat, ChatResponse
from prompts import load
from audio import listen, speak
import sys

# Suppress COM errors that occur when using pycaw to control volume on Windows. These errors are harmless but are hella distracting
def _suppress_com_errors(unraisable):
    if 'COM method call without VTable' in str(unraisable.exc_value):
        return
    sys.__unraisablehook__(unraisable)

sys.unraisablehook = _suppress_com_errors


messages = [{'role': 'system', 'content': load('jarvis-prompt')}]




def main():

    speak("Hello, Sir. What can I do for you.")
    original_volume = TOOL_MAP['get_volume']()['volume']  # get current volume to restore later
    TOOL_MAP['set_volume'](10)  # set volume to 10 when listening to avoid feedback loop
    user_audio_message = listen()
    TOOL_MAP['set_volume'](original_volume)  # set volume back to original when done listening
    print(f"User: {user_audio_message['content']}")
    messages.append(user_audio_message)
    
    # SHOULD ADD ASYNC FOR FASTER TOOL CALLS, BUT THIS IS FINE FOR NOW
    while True:
        response: ChatResponse = chat(
            model='qwen2.5:7b',
            messages=messages,
            tools=TOOLS,
        )
        messages.append(response.message)
        if response.message.tool_calls:
            for tc in response.message.tool_calls:
                if tc.function.name in TOOL_MAP:
                    print(f"Calling {tc.function.name} with arguments {tc.function.arguments}")
                    result = TOOL_MAP[tc.function.name](**tc.function.arguments)
                    print(f"Result: {result}")
                    messages.append({'role': 'tool', 'tool_name': tc.function.name, 'content': str(result)})
                else:
                    print(f"Unknown tool: {tc.function.name}")
                    messages.append({'role': 'tool', 'tool_name': tc.function.name, 'content': f"Error: Tool '{tc.function.name}' not found."})
        else:
            content = response.message.content or ""
            if not content.strip():
                content = "I'm sorry, Sir, I didn't quite catch that. Could you repeat your request?"
            print(f"JARVIS: {content}")
            speak(content)
            break
    
    

if __name__ == "__main__":
    main()