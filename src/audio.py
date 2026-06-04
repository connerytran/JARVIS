
import sounddevice as sd
import numpy as np
from faster_whisper import WhisperModel
from silero_vad import load_silero_vad, VADIterator

WHISPER_MODEL = WhisperModel("base", device="cpu", compute_type="int8")
VAD_MODEL = load_silero_vad()



def listen(sample_rate=16000, chunk_size=512) -> dict:
    vad_iterator = VADIterator( 
        model=VAD_MODEL,
        min_silence_duration_ms=1200,
    )

    audio_buffer = []
    speech_started = False

    print("Listening...")
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
            if speech_started and len(audio_buffer) > 800: 
                return {'role': 'system', 'content': 'User talked for too long. Stopping listening.'}
    
    vad_iterator.reset_states()
    print("Stopped listening, transcribing...")
    full_audio = np.concatenate(audio_buffer)
    segments, _ = WHISPER_MODEL.transcribe(full_audio, beam_size=5, vad_filter=True)
    user_audio = " ".join(seg.text for seg in segments).strip()

    # print(user_audio)
    return {'role': 'user', 'content': f'{user_audio}'}

