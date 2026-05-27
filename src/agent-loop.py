
from tools import TOOLS, TOOL_MAP
from ollama import chat, ChatResponse
from prompts import load




messages = [{'role': 'system', 'content': load('jarvis-prompt')}]
messages.append({'role': 'user', 'content': ' next song.'})

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
