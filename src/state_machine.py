from statemachine import StateMachine, State
from statemachine.contrib.diagram import DotGraphMachine
from services import TOOL_MAP, TOOLS
from prompts import load
from audio import listen, speak
from ollama import chat, ChatResponse

import logging

logger = logging.getLogger(__name__)



class JarvisMachine(StateMachine):
    idle = State("Idle", initial=True)
    listening = State(name="Listening")
    thinking = State(name="Thinking")
    executing = State(name="Executing")
    speaking = State(name="Speaking")

    wake_word_detected = idle.to(listening)
    no_speech_detected_or_timeout = listening.to(idle)
    speech_detected = listening.to(thinking)
    tool_call_generated = thinking.to(executing)
    response_generated = thinking.to(speaking)
    tool_call_completed = executing.to(thinking)
    follow_up_needed = executing.to(speaking)
    follow_up_completed = speaking.to(listening)
    conversation_complete = speaking.to(idle)

    def __init__(self):
        self.messages = [{'role': 'system', 'content': load('jarvis-prompt')}]
        self.volume = None
        self.response = None        
        self.follow_up_flag = False
        super().__init__()


    # ------------- State entry/exit actions --------------

    # ------------- Idle State --------------
    def on_enter_idle(self):
        logger.info("Entering Idle state. Waiting for wake word...")
        self._wait_for_wake_word()          # This function should block until the wake word is detected
        self.wake_word_detected()           # Transition to listening state 

    def _wait_for_wake_word(self):
        # Implement Open wake
        import time
        time.sleep(2)  # Simulate waiting for wake word


    # ------------- Listening State --------------
    def on_enter_listening(self):

        self.volume = TOOL_MAP['get_volume']()['volume']    # get current volume to restore later
        if self.volume > 10:
            TOOL_MAP['set_volume'](10)                          # set volume to 10 when listening to avoid feedback loop
        
        user_speech = listen()
        if user_speech['role'] == 'system':
            logger.info(f"System: {user_speech['content']}")
            self.no_speech_detected_or_timeout()
        else:
            self.messages.append(user_speech)
            logger.info(f"User: {user_speech['content']}")
            self.speech_detected()                       # Transition to thinking state, also triggers the exit function


    def on_exit_listening(self):
        if self.volume is not None:
            TOOL_MAP['set_volume'](self.volume)          # set volume back to original when done listening
        
    
    # ------------- Thinking State --------------
    def on_enter_thinking(self):
        logger.info("Entering Thinking state. Generating response...")
        try:
            self.response: ChatResponse = chat(
                model='qwen2.5:7b',
                messages=self.messages,
                tools=TOOLS,
            )
        except BaseException:
            logger.exception("Error in thinking state")
            raise

        logger.info(f"LLM returned.")
        self.messages.append(self.response.message)
        if self.response.message.tool_calls:
            self.tool_call_generated()
        else:
            self.response_generated()
    

    # ------------- Executing State --------------
    def on_enter_executing(self):        
        for tc in self.response.message.tool_calls:
            if tc.function.name in TOOL_MAP:
                if tc.function.name == 'follow_up':     # We need to check if the tool call is a follow-up request
                    logger.info(f"Calling {tc.function.name}. Follow-up question: {tc.function.arguments['follow_up_question']}")
                    follow_up_question = TOOL_MAP['follow_up'](follow_up_question=tc.function.arguments['follow_up_question'])
                    self.messages.append({'role': 'tool', 'tool_name': tc.function.name, 'content': str(follow_up_question)})
                    self.follow_up_flag = True
                    self.follow_up_needed()             # Transition back to listening state to get follow-up input from user
                    return
                else:
                    logger.info(f"Calling {tc.function.name} with arguments {tc.function.arguments}")
                    result = TOOL_MAP[tc.function.name](**tc.function.arguments)
                    logger.info(f"Result: {result}")
                    self.messages.append({'role': 'tool', 'tool_name': tc.function.name, 'content': str(result)})
            else:
                logger.warning(f"Unknown tool: {tc.function.name}")
                self.messages.append({'role': 'tool', 'tool_name': tc.function.name, 'content': f"Error: Tool '{tc.function.name}' not found."})
                
        self.tool_call_completed()          # Transition back to thinking state to see if more tool calls or if we can generate a response now


    # ------------- Speaking State --------------
    def on_enter_speaking(self):

        if self.follow_up_flag:
            content = self.messages[-1]['content']
            logger.info(f"JARVIS: {content}")
            speak(content)
            self.follow_up_flag = False
            self.follow_up_completed()             # Transition back to listening state to get follow-up input from user
        else: 
            content = self.response.message.content or ""
            if not content.strip():
                content = "I'm sorry, Sir, I didn't quite catch that. Could you repeat your request?"
            logger.info(f"JARVIS: {content}")
            speak(content)
            self.conversation_complete()        # Transition back to idle state to wait for next wake word



# graph = DotGraphMachine(JarvisMachine)  # pass the class, not an instance
# dot = graph()
# dot.write_png("diagram.png")
