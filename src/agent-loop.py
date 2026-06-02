
from tools import TOOLS, TOOL_MAP
from ollama import chat, ChatResponse
from prompts import load
import sounddevice as sd
import numpy as np
from faster_whisper import WhisperModel


messages = [{'role': 'system', 'content': load('jarvis-prompt')}]


whisper_model = WhisperModel("base", device="cpu", compute_type="int8")


def listen(duration=5, sample_rate=16000) -> str:
    print("Listening...")
    # Records audio for a specified duration
    recording = sd.rec(int(duration * sample_rate), samplerate=sample_rate, channels=1, dtype='float32')
    sd.wait()
    print("Stopped listening, transcribing...")
    segments, _ = whisper_model.transcribe(recording.flatten(), beam_size=5, vad_filter=True)
    return " ".join(seg.text for seg in segments).strip()


user_audio = listen()
print(user_audio)
messages.append({'role': 'user', 'content': f'{user_audio}'})


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
                # add the tool result to the messages
                messages.append({'role': 'tool', 'tool_name': tc.function.name, 'content': str(result)})
    else:
        # end the loop when there are no more tool calls
        # final_response = chat(model="qwen2.5:7b", messages=messages, tools=TOOLS, )
        print(response.message.content)
        break
