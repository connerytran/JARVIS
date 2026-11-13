
import os
import queue
import time
from contextlib import closing
from pathlib import Path

# transformers (used by mlx-audio's Whisper tokenizer) resets its own log level when it's first imported, so
# this has to be set before that import. Hides its one-per-run tokenizer warning; errors still show.
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")

import sounddevice as sd
import numpy as np
from mlx_audio.stt import load as load_stt
from mlx_audio.tts.utils import load as load_tts
from silero_vad import load_silero_vad, VADIterator
import openwakeword
from openwakeword.utils import download_models

import warnings
import logging
warnings.filterwarnings('ignore', category=UserWarning, message='.*dropout option.*')
warnings.filterwarnings('ignore', category=FutureWarning, message='.*weight_norm.*')
warnings.filterwarnings('ignore', message='.*unauthenticated.*HF Hub.*')
logging.getLogger("huggingface_hub").setLevel(logging.ERROR)

logger = logging.getLogger(__name__)
STT_MODEL = load_stt("mlx-community/whisper-large-v3-turbo-asr-fp16")
TTS_MODEL = load_tts("mlx-community/Kokoro-82M-bf16")
VAD_MODEL = load_silero_vad()

WAKE_WORD = "hey_jarvis_v0.1"
WAKE_WORD_DIR = Path(__file__).resolve().parent.parent / "models" / "openwakeword"   # outside .venv so a rebuild doesn't wipe it
download_models([WAKE_WORD], target_directory=str(WAKE_WORD_DIR))                     # no-op once the files exist
OPEN_WAKE_WORD = openwakeword.Model(
    wakeword_models=[str(WAKE_WORD_DIR / f"{WAKE_WORD}.onnx")],
    melspec_model_path=str(WAKE_WORD_DIR / "melspectrogram.onnx"),
    embedding_model_path=str(WAKE_WORD_DIR / "embedding_model.onnx"),
    inference_framework="onnx",
)



FIRST_CHUNK_TIMEOUT = 3.0   # seconds to wait for audio after opening; Bluetooth mics (AirPods) can take 1–2 s to start
DEVICE_TIMEOUT = 0.25       # seconds without audio, once it's flowing, before we treat the device as gone (measured: gaps stay within ~7 ms of the 32–80 ms chunk interval)


def _refresh_devices():
    """Makes PortAudio re-read the system's audio devices, so new streams open on the current defaults.
    PortAudio otherwise keeps the list from start-up. No stream may be open while this runs."""
    sd._terminate()
    sd._initialize()


def _mic_chunks(sample_rate, chunk_size):
    """Yields mic chunks (int16 numpy arrays) forever from the default input. If the device stops delivering
    (unplugged) or can't be opened, reopens on whatever the default input is now, so callers never hang."""
    while True:
        _refresh_devices()
        chunks = queue.Queue()

        def on_audio(indata, frames, time_info, status):   # PortAudio calls this on its own thread with each chunk
            chunks.put(indata[:, 0].copy())                # copy: PortAudio reuses indata's memory after we return

        try:
            with sd.InputStream(samplerate=sample_rate, channels=1, dtype='int16', blocksize=chunk_size, callback=on_audio):
                yield chunks.get(timeout=FIRST_CHUNK_TIMEOUT)   # the first chunk can be slow
                while True:
                    yield chunks.get(timeout=DEVICE_TIMEOUT)
        except queue.Empty:
            logger.warning("Microphone stopped sending audio (unplugged?). Reopening on the current default input.")
        except sd.PortAudioError as e:
            logger.warning(f"Couldn't open the microphone ({e}). Retrying in {FIRST_CHUNK_TIMEOUT:.0f} s.")
            time.sleep(FIRST_CHUNK_TIMEOUT)   # no input device at all: don't spin



def wake_word(sample_rate=16000, chunk_size=1280):
    with closing(_mic_chunks(sample_rate, chunk_size)) as mic:
        for chunk in mic:
            prediction = OPEN_WAKE_WORD.predict(chunk)
            if prediction[WAKE_WORD] > 0.85:
                logger.info("Wake word detected.")
                OPEN_WAKE_WORD.reset()
                break



def listen(sample_rate=16000, chunk_size=512) -> dict:
    vad_iterator = VADIterator( 
        model=VAD_MODEL,
        min_silence_duration_ms=1200,
    )

    audio_buffer = []
    speech_started = False

    logger.info("Listening...")
    with closing(_mic_chunks(sample_rate, chunk_size)) as mic:
        for chunk in mic:
            chunk = chunk.astype(np.float32) / 32768.0  # Normalize to [-1, 1] for VAD processing
            audio_buffer.append(chunk)

            event = vad_iterator(chunk)

            if event:
                if 'start' in event:
                    speech_started = True
                if 'end' in event and speech_started:
                    break
                
            # Sample rate of about 16000 and chunk size of 512 means 32 ms per chunk.
            # 32 chunks is about 1 second, so if want to check for no speech after 5 seconds then it would be about 157
            # Chunks * 32 ms = time in ms
            if not speech_started and len(audio_buffer) > 200:
                return {'role': 'system', 'content': 'No speech detected.'}
            if speech_started and len(audio_buffer) > 2000:
                return {'role': 'system', 'content': 'User talked for too long. Stopping listening.'}
    
    vad_iterator.reset_states()
    logger.info("Stopped listening, transcribing...")
    full_audio = np.concatenate(audio_buffer)
    result = STT_MODEL.generate(full_audio, language="en")
    user_audio = result.text.strip()

    return {'role': 'user', 'content': f'{user_audio}'}



SPEAK_MARGIN = 1.0   # seconds past a segment's length before we treat the speaker as gone


def _play(audio, sample_rate) -> bool:
    """Plays audio on the default output and waits until it finishes. Returns False if it didn't finish
    within its length + SPEAK_MARGIN (the device has gone). The stream is closed either way."""
    sd.play(audio, samplerate=sample_rate)
    deadline = time.monotonic() + len(audio) / sample_rate + SPEAK_MARGIN
    try:
        while sd.get_stream().active:          # becomes False once the last sample has played
            if time.monotonic() > deadline:
                return False
            time.sleep(0.05)
        return True
    finally:
        sd.stop()                              # stop and close; must be closed before the next refresh


def speak(text: str, voice='bm_george', speed=1.0):
    if not text or not text.strip():
        return
    _refresh_devices()                         # speak on the current default output; no stream is open here
    for result in TTS_MODEL.generate(text, voice=voice, speed=speed, lang_code='b'):
        audio = np.array(result.audio)
        if not _play(audio, result.sample_rate):
            logger.warning("Speaker stopped playing (unplugged?). Repeating on the current default output.")
            _refresh_devices()
            _play(audio, result.sample_rate)   # one retry; if that fails too, carry on rather than loop

