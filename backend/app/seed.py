from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Domain, Subject, Topic, User

TODO = "TODO: 실제 출제기준 검증 필요"
CURRICULUM = {
    "정보보호 일반": [("암호학", ["대칭키 암호", "공개키 암호", "해시 함수"]), ("정보보호 개론", ["보안 목표", "위협과 취약점", "접근통제"]), ("인증과 권한", ["사용자 인증", "보안 모델", "전자서명"])],
    "시스템 보안": [("운영체제 보안", ["프로세스 보안", "메모리 보호", "파일 시스템 보안"]), ("서버 보안", ["계정 관리", "서비스 hardening", "로그 관리"]), ("악성코드와 대응", ["바이러스", "웜과 트로이목마", "엔드포인트 대응"])],
    "네트워크 보안": [("네트워크 기본 보안", ["TCP/IP 보안", "네트워크 장비", "패킷 분석"]), ("침입 탐지와 방어", ["IDS", "IPS", "방화벽"]), ("무선 및 보안 프로토콜", ["무선랜 보안", "TLS", "VPN"])],
    "응용프로그램 보안": [("웹 애플리케이션 보안", ["SQL Injection", "XSS", "CSRF"]), ("소프트웨어 개발 보안", ["시큐어 코딩", "입력값 검증", "오류 처리"]), ("데이터베이스 보안", ["DB 접근통제", "암호화 컬럼", "감사 로그"])],
    "정보보호 관리체계 및 법규": [("정보보호 관리체계", ["위험관리", "보안 정책", "관리체계 운영"]), ("개인정보 보호", ["개인정보 처리", "개인정보 안전성", "정보주체 권리"]), ("정보보호 관련 법규", ["전자금융 보안", "정보통신망 보호", "법적 책임"])],
}

async def seed_curriculum(session: AsyncSession) -> None:
    if not await session.get(User, 1):
        session.add(User(id=1, name="기본 사용자"))
    if await session.scalar(select(Subject).limit(1)):
        await session.commit()
        return
    for subject_index, (subject_name, domains) in enumerate(CURRICULUM.items(), 1):
        subject = Subject(name=subject_name, weight=20)
        session.add(subject)
        for domain_name, topics in domains:
            domain = Domain(subject=subject, name=f"{domain_name} ({TODO})")
            session.add(domain)
            for topic_name in topics:
                session.add(Topic(domain=domain, name=f"{topic_name} ({TODO})", summary_text=f"{topic_name}의 구조, 목적, 주요 특징과 기본 내용을 정리한다. ({TODO})", keywords=[topic_name, domain_name, subject_name], difficulty_level=(subject_index % 3) + 1))
    await session.commit()
