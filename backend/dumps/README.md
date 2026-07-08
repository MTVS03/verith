# Shared verith SQL dump

이 디렉터리는 **공용 `verith` DB의 canonical 상태를 팀원이 pull 만으로 재현할 수 있게 하는 SQL dump snapshot**
을 담는다.

스키마는 Alembic 이 관리하고, 이 dump 는 **데이터만** 담는다.

## 파일

- `shared_verith_snapshot.sql`
  - `stocks` **2,607**
  - `stock_aliases` **32**
  - `stock_corp_codes` **3,976**

## 팀원 사용 순서

```bash
docker compose up -d postgres

cd backend
uv sync
uv run alembic upgrade head
docker exec -i verith-postgres psql -U verith -d verith < dumps/shared_verith_snapshot.sql
```

확인:

```sql
SELECT COUNT(*) FROM stocks;            -- 2607
SELECT COUNT(*) FROM stock_aliases;     -- 32
SELECT COUNT(*) FROM stock_corp_codes;  -- 3976
```

## 갱신 원칙

- 질문 처리 경로는 계속 **read-only** 이다.
- 이 dump 갱신은 **명시적 관리 작업**이다.
- KIS/DART live sync 결과를 팀과 공유할 필요가 있을 때만 snapshot 을 새로 export 해 커밋한다.
