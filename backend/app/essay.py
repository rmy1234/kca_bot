from dataclasses import dataclass

from app.db.models import Question, Topic
from app.prompts.essay_grading import build_essay_generation_prompt, build_essay_grading_prompt

DISCLAIMER = "이 채점은 참고용이며 실제 실기 시험 채점 기준과 다를 수 있음"


@dataclass
class GeneratedEssay:
    question: str
    model_answer: str
    grading_keywords: list[dict]
    difficulty: int


@dataclass
class EssayFeedback:
    covered_keywords: list[dict]
    missing_keywords: list[dict]
    score: float
    feedback_text: str
    improvement_suggestion: str


class MockEssayLLM:
    async def generate(self, topic: Topic) -> GeneratedEssay:
        keywords = topic.keywords[:3] or [topic.name]
        points = [34, 33, 33]
        grading_keywords = [{"keyword": keyword, "points": points[index]} for index, keyword in enumerate(keywords)]
        model_answer = "와 ".join(keywords) + "을 설명하고 목적과 보안상 고려사항을 제시한다."
        build_essay_generation_prompt(topic)
        return GeneratedEssay(
            question=f"실기 서술형: {topic.name}의 주요 개념과 보안상 고려사항을 설명하시오.",
            model_answer=model_answer,
            grading_keywords=grading_keywords,
            difficulty=topic.difficulty_level,
        )

    async def grade(self, question: Question, answer_text: str) -> EssayFeedback:
        answer_normalized = answer_text.casefold()
        keywords = question.grading_keywords or []
        covered, missing = [], []
        for item in keywords:
            keyword = item["keyword"]
            (covered if keyword.casefold() in answer_normalized else missing).append(item)
        score = round(sum(item["points"] for item in covered), 1)
        build_essay_grading_prompt(question, answer_text)
        if score >= 80:
            feedback = "필수 키워드를 대부분 포함해 핵심 내용이 잘 드러납니다."
            suggestion = "모범답안의 논리 순서와 구체적인 보안 적용 사례를 더해보세요."
        elif score >= 50:
            feedback = "일부 핵심 키워드가 포함되어 있으나 답안의 범위가 부족합니다."
            suggestion = "누락된 키워드를 정의, 목적, 대응 방법과 함께 보완하세요."
        else:
            feedback = "필수 키워드 커버리지가 낮아 핵심 논지가 충분히 드러나지 않습니다."
            suggestion = "모범답안의 핵심 키워드를 중심으로 답안 구조를 다시 작성하세요."
        return EssayFeedback(covered, missing, score, feedback, suggestion)


def get_essay_llm() -> MockEssayLLM:
    return MockEssayLLM()

