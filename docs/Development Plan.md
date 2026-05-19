# Jarvis Voice Assistant - Development Plan

## Project Goal
Build a locally-run JARVIS-like voice assistant using an LLM as the brain, capable of controlling smart home devices and Spotify through voice commands.

---

## Timeline Overview
**Estimated Total Time:** 4-6 weeks (part-time)

---

## Phase 0: Foundation & API Setup
**Duration:** 1-2 weeks  
**Goal:** Get external integrations working before building the core system

**What you'll do:**
- Set up Home Assistant and connect Luvoni lights
- Set up Spotify Developer account and get OAuth working
- Test both APIs manually with curl/Postman
- Document credentials and API endpoints

**Success criteria:**
- Can control lights via Home Assistant API
- Can control Spotify playback via API
- Have all tokens/credentials ready to use

---

## Phase 1: Core Agent Loop (Text-Only)
**Duration:** 1 week  
**Goal:** Build the brain without audio - prove LLM can control actions

**What you'll do:**
- Set up project repository with clean architecture
- Install Ollama and get Llama 3.1 running
- Build agent that takes TEXT input and executes actions
- Integrate Home Assistant and Spotify executors

**Success criteria:**
- Type "turn on lights" → lights turn on
- Type "play music" → Spotify plays
- LLM reliably calls correct functions

**Example:**
```
You type: "Turn on the living room lights"
LLM decides: control_lights(room="living_room", state="on")
Lights turn on
System prints: "Turning on the lights"
```

---

## Phase 2: Add Voice Input (STT + Wake Word)
**Duration:** 1 week  
**Goal:** Replace typing with voice - system listens and transcribes

**What you'll do:**
- Set up microphone input
- Implement openWakeWord ("Hey Jarvis" detection)
- Implement faster-whisper (speech-to-text)
- Build audio pipeline: mic → wake word → STT → agent

**Success criteria:**
- Say "Hey Jarvis, turn on lights" → lights turn on
- Wake word detects reliably
- STT accurately transcribes commands
- Still printing text responses (no TTS yet)

---

## Phase 3: Add Voice Output (TTS)
**Duration:** 3-5 days  
**Goal:** Complete the loop - system talks back

**What you'll do:**
- Implement Kokoro TTS
- Integrate TTS into response flow
- Handle audio conflicts (pause wake word during speech)

**Success criteria:**
- Full voice conversation works
- System responds with clear speech
- Audio doesn't conflict with wake word detection
- Total latency is reasonable (<10 seconds)

---

## Phase 4: Polish & Optimization
**Duration:** 1 week  
**Goal:** Make it robust and demo-ready

**What you'll do:**
- Add error handling for all failure cases
- Implement logging for debugging
- Optimize performance and latency
- Write documentation (README, setup guide)
- Test thoroughly and fix bugs
- Prepare demo scenarios for video

**Success criteria:**
- System runs reliably for extended periods
- Handles errors gracefully
- Well-documented for others to replicate
- Ready to record YouTube video

---

## Phase 5: Optional Enhancements
**Duration:** Ongoing (post-launch)  
**Goal:** Future improvements

**Possible additions:**
- Upgrade to XTTS v2 for better voice quality
- Add cloud LLM fallback for complex queries
- Add more integrations (weather, calendar, etc.)
- Build mobile app for control
- Add conversation memory
- Train custom wake words

---

## Tech Stack Summary

**Hardware:**
- PC: Intel i7 + RTX 2080 Super
- Microphone + speakers

**Software:**
- Wake Word: openWakeWord
- STT: faster-whisper
- LLM: Ollama (Llama 3.1)
- TTS: Kokoro
- Home Control: Home Assistant (Tuya)
- Music: Spotify API
- Language: Python

---

## Success Definition

**MVP (Must Have):**
- Voice-activated with "Hey Jarvis"
- Controls lights (on/off, brightness)
- Controls Spotify (play, pause, search)
- Responds with voice
- Reliable enough for demo

**Nice to Have:**
- Low latency (<5 seconds)
- High accuracy (>90%)
- Multiple scenes/commands
- Advanced controls
