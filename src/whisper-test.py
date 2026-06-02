import sounddevice as sd
import numpy as np
from faster_whisper import WhisperModel

whisper_model = WhisperModel("base", device="cpu", compute_type="int8")


def listen(duration=5, sample_rate=16000) -> str:
    print("Listening...")
    # Records audio for a specified duration
    recording = sd.rec(int(duration * sample_rate), samplerate=sample_rate, channels=1, dtype='float32')
    sd.wait()
    segments, _ = whisper_model.transcribe(recording.flatten(), beam_size=5)
    return " ".join(seg.text for seg in segments).strip()

if __name__ == "__main__":
    transcription = listen()
    print(f"Transcribed text: {transcription}")

