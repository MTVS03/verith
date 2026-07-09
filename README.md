# verith

주식 분석 멀티 에이전트 서비스. 5개 분석 에이전트(기술적 · 기본적/재무 · 뉴스/감성 · 자금흐름/수급 · 산업/섹터)가
분석 리포트를 생성하고, 백엔드가 검증·저장하며, 프론트가 리포트를 보여준다.

환경 세팅(각 서비스 의존성 정의, Next.js 초기화, docker 구성)은 이미 되어 있다.
**클론 → 의존성 설치 → 실행** 순서만 따르면 된다.

## 구성

| 서비스 | 스택 | 포트 |
| --- | --- | --- |
| **AI** | FastAPI | `:9000` |
| **Backend** | FastAPI | `:8000` |
| **Frontend** | Next.js 16 (App Router) | `:3000` |
| **PostgreSQL** | postgres:16 (docker) | 호스트 `:5433` → 컨테이너 `5432` |
| **Redis** | redis:7 (docker) | `:6379` |

```
verith/
├── docker-compose.yml   # PostgreSQL + Redis
├── ai/                  # AI 서버 (:9000)
├── backend/             # 백엔드 서버 (:8000)
├── frontend/            # 프론트 서버 (:3000)
└── docs/                # 공통 설계 문서
```

> **AI 상위 Supervisor 상태:** 질문 해석 → 조건부 resolve → 5-agent fan-out → technical 실행 계층이 연결돼
> 있다. **`BATTERY_TICKERS`(2차전지 10종) 기준 supervisor+technical real smoke 실증 완료**(373220 LG에너지솔루션 ·
> 051910 LG화학 — technical success). technical 은 이제 10종 gate 없이 **형식상 유효한 ticker 를 기본 지원**하고
> 종목명 정본은 backend canonical(`stock_name` 주입)이 담당한다(전체 종목 확장 구조 완료). 확장 종목 real smoke 는
> backend `stocks` seed 후 검증. 상세: [`ai/src/supervisor/README.md`](ai/src/supervisor/README.md).

---

## 0. 사전 준비 (최초 1회)

필요한 도구: **git**, **Docker**, **uv**(Python), **Node.js**.

### Windows — WSL2

Docker는 WSL 안에 설치돼 있어야 하고, **아래 모든 명령은 WSL 터미널에서 실행**한다.
(프로젝트도 가급적 WSL 파일시스템 `~/` 아래에 두면 `--reload`·HMR 감시가 빠르다.)

```bash
# uv
curl -LsSf https://astral.sh/uv/install.sh | sh
# Node.js (nvm)
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash && nvm install --lts
# Docker 동작 확인
docker ps
```

### macOS

```bash
# Homebrew 없으면 먼저: https://brew.sh
brew install git uv node
brew install --cask docker      # 또는: brew install colima docker && colima start
docker ps
```

---

## 1. 클론

```bash
git clone https://github.com/MTVS03/verith.git
cd verith
```

> **아래 파일들은 저장소에 포함되지 않는다.** 팀에서 별도로 공유받아 각 위치에 둔다:
> - `.env` (보안): `ai/.env`, `backend/.env`, `frontend/.env.local`
> - `docker-compose.yml` (루트, 따로 관리)
>
> `.env`의 DB 접속 포트는 호스트 기준 **5433**으로 맞춘다 (compose가 `5433:5432`로 매핑).

---

## 2. DB · Redis 실행 (루트에서)

```bash
docker compose up -d postgres redis
docker ps        # verith-postgres, verith-redis 확인
```

## 3. AI 서버 (`:9000`)

```bash
cd ai
uv sync                                                    # 의존성 설치
uv run uvicorn src.main:app --reload --host 0.0.0.0 --port 9000
```

> 처음 실행 시 모델이 자동 다운로드됩니다.

## 4. Backend 서버 (`:8000`)

```bash
cd backend
uv sync
uv run uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000
```

## 5. Frontend (`:3000`)

Next.js는 이미 초기화되어 있다. 설치 후 실행만 하면 된다.

```bash
cd frontend
npm install       # package.json 기준 설치 (next, react, tailwind, axios, recharts, clsx, lucide-react)
npm run dev
```

접속: http://localhost:3000

---

## 6. 뉴스 DB 스냅샷 복원 (팀 공유 데이터)

뉴스 에이전트가 쌓아둔 데이터(PostgreSQL + Neo4j)를 팀에서 공유한다.
**작성자가 스냅샷을 떠서 커밋**하면, 나머지 팀원은 **`git pull` 받은 뒤 아래 순서대로** 자기 로컬 DB에 복원한다.

> 이 과정은 뉴스 그래프에 **Neo4j**(`verith-neo4j` 컨테이너)가 필요하다. 위 2번에서 postgres·redis만 띄웠다면 neo4j도 함께 띄운다.

**순서가 중요하다** — DB가 안 떠 있거나 스키마가 옛날 상태면 복원이 실패한다.
공통 순서: **① DB 컨테이너 실행 → ② 스키마 최신화(+backend 1회 기동) → ③ 복원 스크립트 실행**

### WSL / macOS / Linux (bash)

```bash
# 1) DB 컨테이너 실행 (verith-postgres / verith-neo4j 가 떠야 함)
docker compose up -d

# 2) 스키마 최신화 + 제약 생성
cd backend
uv run alembic upgrade head            # PG 스키마 최신화
#   그리고 backend 를 한 번 기동  → Neo4j 유니크 제약 생성 (복원 정합/속도)

# 3) 복원 스크립트 실행 (프로젝트 루트 verith/ 에서)
cd ..
./restore_news.sh                      # 권한 없으면  bash restore_news.sh
```

→ [restore_news.sh](restore_news.sh)

### Windows (PowerShell)

```powershell
docker compose up -d

cd backend
.venv\Scripts\python.exe -m alembic upgrade head
#   그리고 backend 를 한 번 기동  → Neo4j 유니크 제약 생성

cd ..
./restore_news.ps1
```

→ [restore_news.ps1](restore_news.ps1)

### 복원 스크립트가 하는 일 (공통)

- `backend/dumps/shared_news_pg.sql` → PostgreSQL 복원 (맨 앞에서 `news`/`news_reports` 를 스냅샷 상태로 초기화 후 주입)
- `backend/dumps/shared_news_neo4j.cypher` → Neo4j 그래프에 반영
- 끝나면 **news 행 수 / neo4j 노드 수**를 찍어 복원이 잘 됐는지 확인시켜 준다

복원 후 backend 가 떠 있었다면 **재기동**하면 완전히 반영된다.

> **임베딩(embedding)은 용량 때문에 스냅샷에서 기본 제외**된다. 임베딩이 필요한 작업이면 따로 채워야 한다.

---

## 실행 확인 (health check)

```bash
curl http://localhost:9000/health   # {"status":"ok","service":"ai"}
curl http://localhost:8000/health   # {"status":"ok","service":"backend"}
# 프론트: 브라우저로 http://localhost:3000
```

각 서비스는 터미널을 따로 띄워 실행한다 (DB/Redis → AI → Backend → Frontend 순).

---

## 종료

```bash
docker compose down          # 컨테이너 중지 (데이터 유지)
docker compose down -v       # 데이터(볼륨)까지 삭제
```

---

## 트러블슈팅

**`Bind for 0.0.0.0:5433 failed: port is already allocated`**
호스트 포트가 이미 점유된 경우다(기본값은 5433). 점유 중인 것을 끄거나,
`docker-compose.yml`의 postgres 포트를 비어 있는 값(예: `"5434:5432"`)으로 바꾸고 `.env`의 DB 포트도 맞춘다.

**`uv sync` 시 Python 버전 관련 메시지**
`requires-python >=3.12` 라서 uv가 알맞은 CPython을 자동으로 받아 `.venv`를 만든다. 그대로 두면 된다.
