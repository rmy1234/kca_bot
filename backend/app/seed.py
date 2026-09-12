from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.auth import hash_password
from app.core.config import get_settings
from app.curriculum import CRITERIA_VERSION, WRITTEN_CRITERIA
from app.db.models import Domain, Subject, Topic, User

def build_summary(subject_name: str, domain_name: str, topic_name: str, detail_items: list[str]) -> str:
    details = "\n".join(f"{index}. {item}" for index, item in enumerate(detail_items, 1))
    return f"[{CRITERIA_VERSION}] {subject_name} > {domain_name} > {topic_name}\n세세항목:\n{details}"

def add_curriculum(session: AsyncSession) -> None:
    for subject_index, (subject_name, question_count, domains) in enumerate(WRITTEN_CRITERIA, 1):
        subject = Subject(name=subject_name, weight=question_count)
        session.add(subject)
        for domain_name, topics in domains:
            domain = Domain(subject=subject, name=domain_name)
            session.add(domain)
            for topic_name, detail_items, keywords in topics:
                session.add(Topic(domain=domain, name=topic_name, summary_text=build_summary(subject_name, domain_name, topic_name, detail_items), keywords=keywords, difficulty_level=(subject_index % 3) + 1, content_version=CRITERIA_VERSION))

async def seed_curriculum(session: AsyncSession) -> None:
    settings = get_settings()
    if settings.admin_email and settings.admin_password:
        if not await session.scalar(select(User).where(User.email == settings.admin_email)):
            session.add(User(name="관리자", email=settings.admin_email, password_hash=hash_password(settings.admin_password), is_admin=True))
    if await session.scalar(select(Subject).limit(1)):
        await session.commit()
        return
    add_curriculum(session)
    await session.commit()
