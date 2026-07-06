from pathlib import Path
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

AI_ROOT = Path(__file__).resolve().parents[3]  # .../ai

# stock_code(6) -> DART corp_code(8) / corpCode.xml 독립 덤프 2종 교차검증 2026-07-02
CORP_CODE_MAP: dict[str, str] = {
    "051910": "00356361",  # LG화학
    "373220": "01515323",  # LG에너지솔루션
    "006400": "00126362",  # 삼성SDI
    "096770": "00631518",  # SK이노베이션
    "086520": "00536541",  # 에코프로
    "247540": "01160363",  # 에코프로비엠
    "003670": "00155276",  # 포스코퓨처엠
    "066970": "00398701",  # 엘앤에프
    "348370": "01011526",  # 엔켐
    "361610": "01386916",  # SK아이이테크놀로지
}

STOCK_NAME_MAP: dict[str, str] = {
    "051910": "LG화학",
    "373220": "LG에너지솔루션",
    "006400": "삼성SDI",
    "096770": "SK이노베이션",
    "086520": "에코프로",
    "247540": "에코프로비엠",
    "003670": "포스코퓨처엠",
    "066970": "엘앤에프",
    "348370": "엔켐",
    "361610": "SK아이이테크놀로지",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(AI_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    DART_API_KEY: str = ""
    DART_BASE_URL: str = "https://opendart.fss.or.kr/api"
    DART_TIMEOUT: float = 10.0
    DEFAULT_FS_DIV: str = "CFS"        # 연결 고정 — OFS 혼용 금지
    DEFAULT_REPRT_CODE: str = "11011"  # 사업보고서(연간)

    # 공용 .env의 QWEN_API_KEY에는 base URL이 들어있음(팀 합의 표기) — alias로 흡수.
    # 추후 팀이 QWEN_BASE_URL로 정정해도 코드 무수정 동작.
    QWEN_BASE_URL: str = Field(
        default="http://192.168.0.35:8000/v1",
        validation_alias=AliasChoices("QWEN_API_KEY", "QWEN_BASE_URL"),
    )
    QWEN_MODEL: str = "Qwen3.6-35B-A3B-UD-Q6_K.gguf"
    LLM_DUMMY_KEY: str = "sk-no-key-required"  # llama-server 무인증 — SDK 형식 충족용