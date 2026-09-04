import asyncio
from app.db.base import Base
from app.db.session import AsyncSessionLocal, engine
from app.seed import seed_curriculum

async def main():
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with AsyncSessionLocal() as session:
        await seed_curriculum(session)
    await engine.dispose()
    print("Curriculum seed completed.")

if __name__ == "__main__":
    asyncio.run(main())

