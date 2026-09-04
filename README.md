# 정보보안기사 AI 학습 프로그램

정보보안기사 필기 5과목과 실기 서술형 범위를 구조화하고, 해당 범위 안에서 AI가 문제를 출제하는 학습 프로그램입니다.

## 프로젝트 문서

- [프로젝트 개요 및 로드맵](docs/PROJECT.md)

## 디렉터리

```text
backend/    FastAPI 백엔드
frontend/   React + Vite 웹 애플리케이션
docs/       프로젝트 설계 및 진행 문서
```

## 요구 환경

- Python 3.11+
- uv
- Node.js 20+
- npm (Node.js 설치 시 포함)
- PostgreSQL (선택 사항: 0단계의 헬스체크와 빈 대시보드는 DB 없이 실행 가능)

## 로컬 실행 방법

### 1. 백엔드

```powershell
cd backend
uv sync
Copy-Item .env.example .env
uv run uvicorn app.main:app --reload
```

백엔드 주소: http://localhost:8000

- 헬스체크: http://localhost:8000/health
- API 문서: http://localhost:8000/docs

### 2. 프론트엔드

새 터미널에서 실행합니다.

```powershell
cd frontend
npm install
npm run dev
```

프론트엔드 주소: http://localhost:5173

> PostgreSQL을 연결할 때는 `backend/.env`의 `DATABASE_URL`을 실제 로컬 DB 접속 정보로 변경합니다. 현재 단계에서는 애플리케이션 시작 시 DB에 연결하지 않으므로 DB가 없어도 화면과 헬스체크를 실행할 수 있습니다.

## 개발 원칙

- 시크릿과 접속 정보는 환경변수로 관리합니다.
- 기능이 필요한 시점에만 도메인 구조를 확장합니다.
- 상세한 범위와 단계별 계획은 `docs/PROJECT.md`를 기준 문서로 삼습니다.
+
### 3. Alembic 마이그레이션(선택)

앱 시작 시 로컬 MVP 테이블과 시드 데이터가 자동으로 준비됩니다. 운영 또는 명시적인 마이그레이션 흐름에서는 다음 명령을 사용합니다.

```powershell
cd backend
uv run alembic upgrade head
uv run python -m scripts.seed
```
