# 정보보안기사 AI 학습 프로그램

정보보안기사 필기 5과목과 실기 서술형 범위를 출제기준에 맞춰 구조화하고, 그 범위 안에서 로컬 LLM이 문제를 출제·검증하는 학습 프로그램입니다.

- 설계와 단계별 진행 기록: [docs/PROJECT.md](docs/PROJECT.md)
- 시험 자료 출처와 이용 조건: [docs/sources/README.md](docs/sources/README.md)

## 디렉터리

```text
backend/    FastAPI 백엔드 (SQLite, Ollama 연동)
frontend/   React + Vite 웹 애플리케이션
docs/       설계 문서와 출제기준 자료
```

## 요구 환경

| 도구 | 버전 | 비고 |
|------|------|------|
| Python | 3.13 (`backend/.python-version`) | 설치돼 있지 않으면 uv가 내려받습니다 |
| [uv](https://docs.astral.sh/uv/) | 최신 | Python 의존성 관리 |
| Node.js | 20.19 이상 또는 22.12 이상 | Vite 8 요구사항 |
| [Ollama](https://ollama.com) | 최신 | 로컬 LLM 실행 |
| GPU | VRAM 8GB 이상 권장 | `qwen3.5:9b`(6.6GB)가 GPU에 모두 올라가야 빠릅니다 |

## 처음 설정하기

### 1. 로컬 LLM 준비

Ollama를 설치하고 실행한 뒤 모델을 내려받습니다.

```powershell
ollama pull qwen3.5:9b
```

### 2. 백엔드

```powershell
cd backend
uv sync
Copy-Item .env.example .env    # macOS/Linux: cp .env.example .env
```

`backend/.env`에서 다음 값을 설정합니다.

- `JWT_SECRET_KEY`: PC마다 새로 생성합니다. `uv run python -c "import secrets; print(secrets.token_hex(32))"`
- `ADMIN_EMAIL`, `ADMIN_PASSWORD`: 콘텐츠 관리 화면을 쓰려면 설정합니다. 서버를 처음 시작할 때 관리자 계정이 만들어집니다.

```powershell
uv run uvicorn app.main:app --reload
```

- 백엔드: http://localhost:8000 (API 문서: `/docs`, 헬스체크: `/health`)
- 첫 시작 시 `backend/kca_bot.db`가 만들어지고, 2023-2026 출제기준 커리큘럼(5과목, 38개 세부항목)이 자동으로 들어갑니다.

### 3. 프론트엔드

새 터미널에서 실행합니다.

```powershell
cd frontend
npm ci
npm run dev
```

- 프론트엔드: http://localhost:5173
- 백엔드 주소나 포트를 바꿨다면 `frontend/.env.example`을 `frontend/.env`로 복사해 `VITE_API_BASE_URL`을 고치고, `backend/.env`의 `CORS_ORIGINS`에 프론트엔드 주소를 넣습니다.

## 테스트

```powershell
cd backend
uv run pytest
```

테스트는 Ollama나 외부 API 없이 실행됩니다.

## 저장소에 포함하지 않는 파일

| 파일 | 제외 이유 | 새 PC에서 할 일 |
|------|----------|---------------|
| `backend/.env` | JWT 비밀키, 관리자 비밀번호 | `.env.example`을 복사해 새로 작성 |
| `backend/kca_bot.db` | 계정, 풀이 기록, 업로드한 학습 자료 | 첫 실행 시 자동 생성 |
| 출제기준 2027-2029판 PDF·TXT | 재배포 이용 허락 미확인 | [docs/sources/README.md](docs/sources/README.md)의 링크에서 직접 내려받기 |

학습 기록은 git으로 옮겨지지 않습니다. 다른 PC로 옮기려면 백엔드를 끈 상태에서 `backend/kca_bot.db` 파일을 직접 복사하세요.

## LLM 설정 바꾸기

`backend/.env`에서 설정하고, 바꾼 뒤에는 백엔드를 다시 시작합니다.

- 다른 로컬 모델: `OLLAMA_MODEL`
- Ollama 클라우드 모델과 로컬 대체 모델: `OLLAMA_MODEL=gemma4:cloud`, `OLLAMA_FALLBACK_MODEL=qwen3.5:9b`. `ollama signin`이 필요하고, 프롬프트가 Ollama 서버로 전송됩니다.
- Gemini API: `LLM_PROVIDER=gemini`, `GEMINI_API_KEY`

## Alembic 마이그레이션 (선택)

앱 시작 시 테이블과 시드 데이터가 자동으로 준비됩니다. 명시적인 마이그레이션 흐름이 필요하면 다음을 사용합니다.

```powershell
cd backend
uv run alembic upgrade head
uv run python -m scripts.seed
```

## 개발 원칙

- 시크릿과 접속 정보는 환경변수(`.env`)로만 관리하고 커밋하지 않습니다.
- 기능이 필요한 시점에만 도메인 구조를 확장합니다.
- 상세한 범위와 단계별 계획은 `docs/PROJECT.md`를 기준 문서로 삼습니다.
