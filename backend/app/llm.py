from dataclasses import dataclass
from typing import Protocol

from app.db.models import Topic
from app.prompts.question_generation import build_question_prompt

@dataclass
class GeneratedQuestion:
    question: str
    choices: list[str]
    answer_index: int
    explanation: str
    difficulty: int

class QuestionGenerator(Protocol):
    async def generate(self, topic: Topic, count: int, retrieved_context: list[str] | None = None, reference_questions: list[str] | None = None) -> list[GeneratedQuestion]: ...

class MockQuestionGenerator:
    async def generate(self, topic: Topic, count: int, retrieved_context: list[str] | None = None, reference_questions: list[str] | None = None) -> list[GeneratedQuestion]:
        prompt_context = build_question_prompt(topic, retrieved_context, reference_questions)
        keyword = topic.keywords[0] if topic.keywords else topic.name
        return [GeneratedQuestion(question=f"[Mock {i + 1}] Which choice best matches the topic '{topic.name}'?", choices=[keyword, "Unrelated concept", "Out-of-scope concept", "None of the above"], answer_index=0, explanation=f"Generated with {len(prompt_context)} characters of Topic and RAG context.", difficulty=topic.difficulty_level) for i in range(count)]

def get_question_generator() -> QuestionGenerator:
    return MockQuestionGenerator()

async def verify_question(question: GeneratedQuestion, topic: Topic) -> tuple[bool, str | None]:
    if len(question.choices) != 4:
        return False, "choices must contain exactly four items"
    if not 0 <= question.answer_index < 4:
        return False, "answer_index must be between 0 and 3"
    if len(set(question.choices)) != 4:
        return False, "choices must be unique"
    if topic.name.lower() not in question.question.lower():
        return False, "question is outside the selected topic"
    return True, None
