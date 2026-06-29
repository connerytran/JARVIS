
import sounddevice as sd
import numpy as np
from faster_whisper import WhisperModel
from silero_vad import load_silero_vad, VADIterator
import openwakeword
from kokoro import KPipeline
from pycaw.pycaw import AudioUtilities

import warnings
import logging
warnings.filterwarnings('ignore', category=UserWarning, message='.*dropout option.*')
warnings.filterwarnings('ignore', category=FutureWarning, message='.*weight_norm.*')
warnings.filterwarnings('ignore', message='.*unauthenticated.*HF Hub.*')
logging.getLogger("huggingface_hub").setLevel(logging.ERROR)

logger = logging.getLogger(__name__)
WHISPER_MODEL = WhisperModel("small.en", device="cuda", compute_type="int8")
VAD_MODEL = load_silero_vad()
KOKORO_PIPELINE = KPipeline(lang_code='b', repo_id='hexgrad/Kokoro-82M')  # https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md#british-english for the voices
OPEN_WAKE_WORD = openwakeword.Model(wakeword_models=["hey_jarvis_v0.1"], inference_framework="onnx")
volumes = {}  # Dictionary to store the original volumes of other applications



def _duck_audio(ducked_volumes: dict):
    """Lower the other application's volume to avoid feedback loop when listening."""
    try:
        if AudioUtilities.GetAllSessions() is None:
            return
        for session in AudioUtilities.GetAllSessions():
            if not session.Process or session.Process.name() == "python.exe":
                continue

            vol = session.SimpleAudioVolume
            if vol:
                ducked_volumes[session.Process.name()] = vol.GetMasterVolume()
                vol.SetMasterVolume(0.3, None)
    except Exception as e:
        logger.error(f"Failed to duck audio: {session.Process.name() if session.Process else 'Unknown'}: {str(e)}")



def _restore_audio(ducked_volumes: dict):
    
    """Restore the other application's volume after listening."""
    try:
        for session in AudioUtilities.GetAllSessions():
            if not session.Process or session.Process.name() == "python.exe":
                continue

            vol = session.SimpleAudioVolume
            if vol and session.Process.name() in ducked_volumes:
                vol.SetMasterVolume(ducked_volumes[session.Process.name()], None)  # Restore volume
        logger.info("Audio restored to previous levels.")
    except Exception as e:
        logger.error(f"Failed to restore audio: {session.Process.name() if session.Process else 'Unknown'}: {str(e)}")



def wake_word(sample_rate=16000, chunk_size=1280):
    with sd.InputStream(samplerate=sample_rate, channels=1, dtype='int16', blocksize=chunk_size) as stream:
        while True:
            chunk, _ = stream.read(chunk_size)
            chunk = np.frombuffer(chunk, dtype=np.int16)
            prediction = OPEN_WAKE_WORD.predict(chunk)
            if prediction["hey_jarvis_v0.1"] > 0.5: 
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
    _duck_audio(ducked_volumes=volumes)  # Lower the other application's volume to avoid feedback loop when listening

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
                _restore_audio(ducked_volumes=volumes)  # Restore the other application's volume after listening
                return {'role': 'system', 'content': 'No speech detected.'}
            if speech_started and len(audio_buffer) > 800: 
                _restore_audio(ducked_volumes=volumes)  # Restore the other application's volume after listening
                return {'role': 'system', 'content': 'User talked for too long. Stopping listening.'}
    
    vad_iterator.reset_states()
    logger.info("Stopped listening, transcribing...")
    full_audio = np.concatenate(audio_buffer)
    segments, _ = WHISPER_MODEL.transcribe(full_audio, beam_size=5, language="en")
    user_audio = " ".join(seg.text for seg in segments).strip()

    _restore_audio(ducked_volumes=volumes)  # Restore the other application's volume after listening
    return {'role': 'user', 'content': f'{user_audio}'}



def speak(text: str, voice='bm_george', speed=1.0):
    if not text or not text.strip():
        return
    _duck_audio(ducked_volumes=volumes)  # Lower the other application's volume to avoid feedback loop when speaking
    for _, _, audio in KOKORO_PIPELINE(text, voice=voice, speed=speed):
        sd.play(audio, samplerate=24000)
        sd.wait()
    _restore_audio(ducked_volumes=volumes)  # Restore the other application's volume after speaking


