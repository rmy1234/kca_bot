"""기존 커리큘럼을 app/curriculum.py의 출제기준으로 교체한다.

사용자 계정은 유지하고, 커리큘럼에 연결된 학습 데이터(문제, 풀이, 복습 일정, 임베딩,
업로드 문서, 참고 문제)는 삭제한다. 옵션 없이 실행하면 삭제 대상 건수만 출력한다.

    uv run python -m scripts.reseed_curriculum         # 건수 확인
    uv run python -m scripts.reseed_curriculum --yes   # SQLite 백업 후 교체
"""
import argparse
import asyncio
from datetime import datetime
from pathlib import Path
import shutil

from sqlalchemy import delete, func, select
from sqlalchemy.engine import make_url

from app.core.config import get_settings
from app.curriculum import CRITERIA_VERSION
from app.db.base import Base
from app.db.models import Domain, GenerationLog, Question, ReferenceQuestion, ReviewSchedule, SourceDocument, Subject, Topic, TopicEmbedding, UserAnswerLog, UserEssayAnswer
from app.db.session import AsyncSessionLocal, engine
from app.seed import add_curriculum

# 자식 테이블부터 삭제한다.
CURRICULUM_TABLES = [UserEssayAnswer, UserAnswerLog, ReviewSchedule, GenerationLog, ReferenceQuestion, TopicEmbedding, SourceDocument, Question, Topic, Domain, Subject]


def backup_sqlite() -> Path | None:
    url = make_url(get_settings().database_url)
    if not url.drivername.startswith("sqlite") or not url.database:
        return None
    database = Path(url.database)
    backup = database.with_name(f"{database.name}.{datetime.now():%Y%m%d-%H%M%S}.bak")
    shutil.copy2(database, backup)
    return backup


async def main(confirmed: bool) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with AsyncSessionLocal() as session:
        for model in CURRICULUM_TABLES:
            count = await session.scalar(select(func.count()).select_from(model))
            print(f"{model.__tablename__}: {count}")
        if not confirmed:
            print(f"\n위 데이터를 삭제하고 '{CRITERIA_VERSION}' 커리큘럼으로 교체하려면 --yes를 붙여 실행하세요.")
            await engine.dispose()
            return
        backup = backup_sqlite()
        if backup:
            print(f"\n백업: {backup}")
        for model in CURRICULUM_TABLES:
            await session.execute(delete(model))
        add_curriculum(session)
        await session.commit()
        topic_count = await session.scalar(select(func.count()).select_from(Topic))
    await engine.dispose()
    print(f"'{CRITERIA_VERSION}' 커리큘럼으로 교체했습니다. Topic {topic_count}개")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--yes", action="store_true", help="삭제와 교체를 실행한다")
    asyncio.run(main(parser.parse_args().yes))
