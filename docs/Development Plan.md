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
- [x] Set up Home Assistant and connect Luvoni lights
- [x] Set up Spotify Developer account and get OAuth working
- [x] Test both APIs manually with curl/Postman
- [x] Document credentials and API endpoints

**Success criteria:**
- [x] Can control lights via Home Assistant API
- [x] Can control Spotify playback via API
- [x] Have all tokens/credentials ready to use

---

## Phase 1: Core Agent Loop (Text-Only)
**Duration:** 1 week  
**Goal:** Build the brain without audio - prove LLM can control actions

**What you'll do:**
- [x] Set up project repository with clean architecture
- [x] Install Ollama and get Qwen 2.5 7B running
- [x] Create tools directory structure (tools/spotify.py, tools/home_assistant.py)
- [ ] Build complete Spotify tool functions (play, pause, skip, etc.)
- [ ] Build complete Home Assistant tool functions (lights control, brightness, etc.)
- [ ] Build agent orchestrator that handles tool calling loop
- [ ] Test end-to-end: type command → LLM calls function → action executes

**Success criteria:**
- [ ] Type "turn on lights" → lights turn on
- [ ] Type "play music" → Spotify plays
- [ ] LLM reliably calls correct functions with correct parameters
- [ ] System handles errors gracefully (API failures, wrong commands, etc.)

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
- [ ] Set up microphone input handling
- [ ] Implement openWakeWord ("Hey Jarvis" detection)
- [ ] Implement faster-whisper (speech-to-text)
- [ ] Build audio pipeline: mic → wake word → STT → agent
- [ ] Tune wake word threshold for reliability
- [ ] Handle audio buffering and recording
- [ ] Implement silence detection via Silero VAD (replace fixed-duration recording)
- [ ] Refactor agent-loop.py into explicit state machine (IDLE → LISTENING → THINKING → SPEAKING/TOOL_CALLING)

**Success criteria:**
- [ ] Say "Hey Jarvis, turn on lights" → lights turn on
- [ ] Wake word detects reliably (low false positives/negatives)
- [ ] STT accurately transcribes commands
- [ ] End-to-end voice → action works
- [ ] Still printing text responses (no TTS yet)

---

## Phase 3: Add Voice Output (TTS)
**Duration:** 3-5 days  
**Goal:** Complete the loop - system talks back

**What you'll do:**
- [ ] Implement Kokoro TTS
- [ ] Integrate TTS into agent response flow
- [ ] Add audio output handling (speakers)
- [ ] Handle audio state management (pause wake word during TTS)
- [ ] Optimize response latency

**Success criteria:**
- [ ] Full voice conversation works
- [ ] System responds with clear speech
- [ ] No audio conflicts (wake word pauses during TTS playback)
- [ ] Total latency is reasonable (<10 seconds)
- [ ] Natural conversation flow

---

## Phase 4: Polish & Optimization
**Duration:** 1 week  
**Goal:** Make it robust and demo-ready

**What you'll do:**
- [ ] Add comprehensive error handling for all failure cases
- [ ] Implement logging for debugging
- [ ] Optimize performance and reduce latency where possible
- [ ] Write documentation (README, setup guide, architecture docs)
- [ ] Test thoroughly and fix bugs
- [ ] Prepare demo scenarios for YouTube video
- [ ] Create configuration system for easy customization

**Success criteria:**
- [ ] System runs reliably for extended periods
- [ ] Handles errors gracefully (network failures, API errors, etc.)
- [ ] Well-documented for others to replicate
- [ ] Ready to record YouTube video
- [ ] Clean, maintainable code

---

## Phase 5: Optional Enhancements
**Duration:** Ongoing (post-launch)  
**Goal:** Future improvements

**Possible additions:**
- [ ] Upgrade to XTTS v2 for better voice quality with voice cloning
- [ ] Add cloud LLM fallback (Claude/GPT-4) for complex queries
- [ ] Add more integrations (weather, calendar, email, news, etc.)
- [ ] Build mobile app for control and monitoring
- [ ] Add conversation memory and context
- [ ] Train custom wake words
- [ ] Implement RAG for personal knowledge base
- [ ] Add auto-start Spotify functionality
- [ ] Multi-room support with different wake words
- [ ] Custom routines and macros
- [ ] Improved music search (fuzzy matching for artist names)

---

## Tech Stack Summary

**Hardware:**
- PC: Intel i7 + RTX 2080 Super
- Microphone + speakers

**Software:**
- Wake Word: openWakeWord
- STT: faster-whisper
- LLM: Ollama (Qwen 2.5 7B)
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