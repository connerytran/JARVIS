# Jarvis Voice Assistant - High-Level System Components

## Overview
Building a locally-run voice assistant system using LLMs as the brain, capable of controlling smart home devices and Spotify.

---

## **1. Voice Input Pipeline**
- **Microphone** (hardware you already have)
- **Wake Word Detection** ("Hey Jarvis" trigger)
- **Speech-to-Text** (converts your voice → text)
- **Audio preprocessing** (noise reduction, voice activity detection)
- **Silero VAD** (drives the recording loop — stops capture after silence, distinct from faster-whisper's internal `vad_filter`)

---

## **2. The Brain (LLM Layer)**
- **Local LLM runtime** (Ollama, llama.cpp, etc.)
- **Model selection** (which model to run)
- **Function/Tool calling system** (teaches LLM what it can do)
- **Context/memory management** (remembers conversation)
- **Optional: Cloud LLM fallback** (swap modes)

---

## **3. Action Execution Layer**
- **Home Assistant integration** (lights control)
- **Spotify API integration** (music control)
- **Function routing** (brain says "turn on lights" → executes correct API call)
- **Error handling** (what if lights don't respond?)

---

## **4. Response Pipeline**
- **Text-to-Speech** (LLM response → voice)
- **Audio output** (speakers)
- **Optional: Visual feedback** (terminal output, LED indicators, etc.)

---

## **5. Orchestration/Glue**
- **Main application loop** (ties everything together)
- **State management** — explicit states:
  - `IDLE` — waiting for wake word / hotkey
  - `LISTENING` — capturing and buffering audio; VAD decides when to stop
  - `THINKING` — LLM is processing the transcription
  - `SPEAKING` — TTS is playing back the response
  - `TOOL_CALLING` — an action is being executed (useful for UI feedback)
- **Configuration** (settings, API keys, model selection)
- **Logging/debugging** (crucial for troubleshooting)

---

## **Supporting Infrastructure**

### **6. Home Automation Backend**
- **Home Assistant setup** (the hub for your smart home)
- **Device discovery/pairing** (connecting your actual lights)
- **API/webhook configuration**

### **7. Development Environment**
- **Python environment** (main language)
- **Dependencies management** (pip/conda)
- **GPU setup** (CUDA for your 2080 Super)
- **Version control** (Git - document your journey)

---

## **Hardware Requirements**
- **Main PC:** i7 Intel + 2080 Super (8GB VRAM)
- **Microphone:** Connected to PC
- **Smart Lights:** (Currently controlled via Alexa)
- **Speakers:** For audio output

---

## **Phased Development Approach**

### **Phase 1: MVP Core Loop** (Weekend project)
```
Text input → Local LLM → Function calling → Control lights/Spotify
```
- Prove the brain works
- Build the integration layer
- No audio complexity yet

### **Phase 2: Add Voice Input** (Week 2-3)
```
Push-to-talk → Speech-to-Text → [existing system]
```
- Hold spacebar/button to talk
- No wake word complexity yet

### **Phase 3: Wake Word + Always Listening** (Week 4+)
```
Always listening → "Hey Jarvis" → [existing system]
```
- Wake word detection
- Audio pipeline management
- False positive handling

### **Phase 4: Text-to-Speech Response**
```
[existing system] → TTS → Audio output
```
- Voice response system
- Natural conversation flow

