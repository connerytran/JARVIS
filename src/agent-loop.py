
from tools import TOOLS, TOOL_MAP
from ollama import chat, ChatResponse
from prompts import load
from audio import listen


messages = [{'role': 'system', 'content': load('jarvis-prompt')}]




def main():

    # current_volume = TOOL_MAP['get_volume']()['volume']  # get current volume to restore later
    # TOOL_MAP['set_volume'](10)  # set volume to 10 when listening to avoid feedback loop
    user_audio_message = listen()
    print(f"User: {user_audio_message['content']}")
    messages.append(user_audio_message)
    
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
    
    # if current_volume != TOOL_MAP['get_volume']()['volume']:
    #     TOOL_MAP['set_volume'](current_volume)  # restore original volume after done listening and responding
    

if __name__ == "__main__":
    main()