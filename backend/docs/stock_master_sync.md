# Stock Master Sync — KIS 종목마스터 → stocks

`docs/stock_master_sync.md`

Backend 가 `stocks`(공통 종목 마스터)를 KIS 공개 종목마스터로 동기화하는 경계의 **정본**.
물리 스키마는 [`schema.md`](schema.md), Resolver 응답 의미는 [`stock_resolver.md`](stock_resolver.md).

> **AI 패키지 import 없음.** 파싱 규칙은 KIS 공식 예제를 근거로 backend 가 독자 구현한다.
> **이번 단계는 sync 기반 구현이며, 실제 전체 마스터 적용은 수동 `--apply` 로만** 한다.

## 1. 데이터 출처 (공식 근거)
- KIS 공식 예제: `koreainvestment/open-trading-api` 의 `stocks_info/`
  (`kis_kospi_code_mst.py`·`kis_kosdaq_code_mst.py` 파서, `종목마스터정보(코스피/코스닥).h` 헤더).
- 마스터 URL(인증 불필요): `https://new.real.download.dws.co.kr/common/master/{kospi_code,kosdaq_code}.mst.zip`
- 포맷: ZIP → **cp949 고정폭**. 레코드 = `front` + `tail`.
  - `front = row[:len-TAIL]`: 단축코드 `[0:9]` · 표준코드 `[9:21]` · 한글명 `[21:]`
  - `tail = row[-TAIL:]`: 고정폭 필드 (**KOSPI 227 / KOSDAQ 221** — 시장별 개수·위치 상이)

## 2. 사용하는 tail 필드 (offset·width) — 실데이터 검산 확정
`--inspect` 실데이터 앵커 검산으로 확정한 값이다(공식 field_specs 누적합은 tail 길이가 1 커서 group 이
' S'로 밀렸었다 — 실측으로 교정). **KOSPI/KOSDAQ 위치가 다르므로 시장별 spec 을 둔다**
(`src/api/constants/kis_master.py`).

| 필드 | KOSPI (offset,w) | KOSDAQ (offset,w) | 용도 |
|---|---|---|---|
| 증권그룹구분코드(그룹코드) | (0,2) | (0,2) | 1차 포함/제외 (주권=`ST`) |
| ETP 상품구분코드 | (35,1) | (18,1) | ETF/ETN 이중 제외 |
| 기업인수목적회사여부(SPAC) | (29,1) | (24,1) | SPAC 제외(공식 플래그) |
| 우선주 구분 코드 | (158,1) | (152,1) | 포함(제거 안 함), is_preferred 통계용 |

> **offset·값 semantics 검산 완료(`FLAG_VALUE_SEMANTICS_VERIFIED=True`).** 앵커: 005930 삼성전자(주권
> `ST`·etp N·pref 0), 005935 삼성전자우(pref set), 069500 KODEX200(ETF `EF`·etp Y·group 제외), 293940
> 신한알파리츠(`RT`), KOSDAQ 디비금융제N호스팩(spac set). 1차 포함 판정은 그룹코드==`ST`, SPAC/ETP 는
> **보조 제외**(fail-open — KOSPI spac·KOSDAQ etp/pref 는 앵커 부재로 값 미검증이나 false 제외 0이고
> ETF/ETN/REIT 는 group 으로 이미 제외됨). 실측 규모: KOSPI 주권 ~893 / KOSDAQ ~1,714.

## 3. 포함/제외 (공식 필드 우선)
1. **증권그룹구분코드 == `ST`(주권)** 만 포함 — 보통주·우선주 모두 ST. 그 외(EF=ETF·EN=ETN·RT=REIT·…) 제외.
2. AND **SPAC 플래그 미설정** — SPAC 제외(공식 플래그 우선; 종목명 "스팩"은 보조 검증만).
3. AND **ETP 플래그 미설정** — ETF/ETN 이중 제외.
4. **우선주는 포함**(제거 안 함). 단축코드가 6자리 숫자가 아니면 제외.

> "6자리 숫자라서 주식" 같은 편법 금지 — 반드시 공식 tail 필드로 판정한다. ETF/ETN/REIT/SPAC 지원은
> 향후 `instrument_type` 계약·Agent 정책 마련 후 별도 확장.

## 4. 동기화 정책
- **신규 stock_code → INSERT / 기존 + 이름·시장 변경 → UPDATE / 변경 없음 → 그대로.**
- **누락 종목(마스터에 없음) → 삭제·비활성화 안 함.** 한 번의 누락을 상장폐지로 판단하지 않는다
  (상장폐지·거래정지는 별도 소스·유예 규칙 마련 후).
- `updated_at` 은 **실제 이름/시장 변경이 있을 때만** 갱신(전체 row 무조건 갱신 금지).
- `stock_aliases` 는 건드리지 않는다. 공식 이름을 alias 로 복제하지 않는다. 이름 변경 시 이전 이름을
  `former_name` alias 로 **자동 생성하지 않는다**(확인된 데이터에 한해 별도 큐레이션).
- **두 시장(KOSPI/KOSDAQ) fetch·파싱·검증 완료 후 단일 트랜잭션**. 한 시장 실패 시 반영 0건.
- 앞자리 0·문자열 stock_code·market 보존.

## 5. 안전장치(과소 데이터)
- 시장별 결과 0건 → 실패. 보수적 **하한 미만 → 실패**(정확한 하한은 실데이터 검산 후 확정 — 코드에
  실제 총수를 고정하지 않는다). **시장 간 stock_code 중복 → 실패.** 제외 유형별 count 를 dry-run 출력.

## 6. 실행 (수동 전용 — 네트워크)
```bash
cd backend
uv run python -m scripts.sync_stocks             # dry-run: 다운로드·파싱·검증·diff, DB 미변경(기본)
uv run python -m scripts.sync_stocks --inspect    # 앵커 종목 tail 필드 검산, DB 미변경
uv run python -m scripts.sync_stocks --apply       # 실제 반영(commit)
```
- **기본은 dry-run**(DB 미변경). `--apply` 일 때만 commit.
- `--inspect` 는 **KOSPI**(삼성전자 005930 ST·삼성전자우 005935 우선주·KODEX200 069500 EF·신한알파리츠
  293940 RT)와 **KOSDAQ**(에코프로 086520·에코프로비엠 247540 ST) 앵커 + **그룹≠ST 자동 검출 제외 예시**의
  `group/spac/etp/pref` 를 출력해 양 시장 offset/값 semantics 를 **실데이터로 검산**한다.
- ⚠️ 실행 전 외부 네트워크 호출·URL·DB 변경 여부(dry-run/`--apply`)를 확인하고 승인 후 실행한다.
- 앱 startup·pytest 에서 실행하지 않는다. 테스트는 fake downloader/fixture bytes 사용.

## 7. bootstrap seed 와의 구분
- `scripts/seed_stocks`(10종, `ON CONFLICT DO NOTHING`) = **개발 bootstrap**(기존 값 보호).
- `scripts/sync_stocks`(전체 마스터, insert/update) = **마스터 최신화**.
- `stocks`(공통 마스터)와 Technical 10종 지원 정책(`BATTERY_TICKERS`)은 **별개** — sync 로 stocks 가
  커져도 Technical 지원 범위는 자동 확대되지 않는다.

## 8. 현재 한계 / 후속
- 이번 브랜치는 **schema/migration 변경 없음**(`is_active`/`status`/`last_synced_at`/`listed_at`/
  `delisted_at` 추가 안 함). 상장폐지·sync 이력은 데이터·정책 확정 후 별도(예: `stock_master_sync_runs`).
- 실데이터 `--apply` 는 아직 수행 전 — dry-run/`--inspect` 검산 후 승인받아 실행한다.
