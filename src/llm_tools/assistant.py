
def follow_up(follow_up_question: str):
    """
    Use this tool when you need more information from the user before you can complete their request.
    Call this INSTEAD of asking a question in your response text — never ask the user a question directly in your reply.
    Pass the question you want to ask as follow_up_question.
    If you need to perform other actions first (e.g. search before asking), call those tools first, then call follow_up last.
    """
    return follow_up_question
