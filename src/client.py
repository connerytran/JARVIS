
from tools.spotify import TOOLS
from ollama import chat, ChatResponse


available_tools = {f.__name__: f for f in TOOLS}


messages = [{'role': 'user', 'content': 'Can you play feel it by d four vid? also respond as if you were Jarvis from the Marvel Cinematic Universe. Refer to me as sir. Respond simply and curteously.'}]

while True:
    response: ChatResponse = chat(
        model='qwen2.5:7b',
        messages=messages,
        tools=TOOLS,
    )
    messages.append(response.message)
    if response.message.tool_calls:
        for tc in response.message.tool_calls:
            if tc.function.name in available_tools:
                print(f"Calling {tc.function.name} with arguments {tc.function.arguments}")
                result = available_tools[tc.function.name](**tc.function.arguments)
                print(f"Result: {result}")
                # add the tool result to the messages
                messages.append({'role': 'tool', 'tool_name': tc.function.name, 'content': str(result)})
    else:
        # end the loop when there are no more tool calls
        # final_response = chat(model="qwen2.5:7b", messages=messages, tools=TOOLS, )
        print(response.message.content)
        break
  # continue the loop with the updated messages



# response = chat(model="qwen2.5:7b", messages=messages, tools=TOOLS, )

# messages.append(response.message)
# if response.message.tool_calls:
#   # only recommended for models which only return a single tool call
#   call = response.message.tool_calls[0]
#   result = TOOLS[0](**call.function.arguments)
#   # add the tool result to the messages
#   messages.append({"role": "tool", "tool_name": call.function.name, "content": str(result)})

#   final_response = chat(model="qwen2.5:7b", messages=messages, tools=TOOLS, )
#   print(final_response.message.content)
