
import os
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



def wake_word(sample_rate=16000, chunk_size=1280):
    with sd.InputStream(samplerate=sample_rate, channels=1, dtype='int16', blocksize=chunk_size) as stream:
        while True:
            chunk, _ = stream.read(chunk_size)
            chunk = np.frombuffer(chunk, dtype=np.int16)
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
    with sd.InputStream(samplerate=sample_rate, channels=1, dtype='int16', blocksize=chunk_size) as stream:
        while True:
            chunk, _ = stream.read(chunk_size)
            chunk = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768.0  # Normalize to [-1, 1] for VAD processing
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



def speak(text: str, voice='bm_george', speed=1.0):
    if not text or not text.strip():
        return
    for result in TTS_MODEL.generate(text, voice=voice, speed=speed, lang_code='b'):
        sd.play(np.array(result.audio), samplerate=result.sample_rate)
        sd.wait()

