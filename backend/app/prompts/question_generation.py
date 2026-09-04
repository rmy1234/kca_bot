SYSTEM_PROMPT = """You generate multiple-choice questions for the Information Security Engineer exam.
Use only the selected Topic summary, keywords, and retrieved RAG context.
Never use knowledge outside that Topic scope.
Reference questions are style and difficulty references only. Never copy, quote, or closely paraphrase them;
create a new question that tests the same allowed Topic concept.
Return exactly one JSON object with no markdown:
{"question":"...", "choices":["...","...","...","..."], "answer_index":0, "explanation":"...", "difficulty":1}
choices must contain exactly four unique strings; answer_index must be 0-3; difficulty must be 1-3.
"""

VERIFICATION_PROMPT = """Verify that exactly one choice is correct, every other choice is actually wrong,
and the question stays within the supplied Topic and RAG context. Return only:
{"is_valid":true,"reason":null}
"""

def build_question_prompt(topic, retrieved_context=None, reference_questions=None):
    context = "\n".join(retrieved_context or []) or "No retrieved context"
    references = "\n".join(reference_questions or []) or "No reference questions"
    return f"{SYSTEM_PROMPT}\nTopic: {topic.name}\nSummary: {topic.summary_text}\nKeywords: {', '.join(topic.keywords)}\nRAG context:\n{context}\nStyle-only reference questions:\n{references}"

def build_verification_prompt(topic, question):
    return f"{VERIFICATION_PROMPT}\nTopic: {topic.name}\nQuestion: {question.question}\nChoices: {question.choices}"
