from pathlib import Path
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

AI_ROOT = Path(__file__).resolve().parents[4]  # .../ai

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

    # Team convention: QWEN_API_KEY stores the OpenAI-compatible Qwen base URL.
    # QWEN_BASE_URL is also accepted for local overrides.
    QWEN_BASE_URL: str = Field(
        default="http://pbd.mtvs2026.work:8000/v1",
        validation_alias=AliasChoices("QWEN_API_KEY", "QWEN_BASE_URL"),
    )
    QWEN_MODEL: str = "Qwen3.6-35B-A3B-UD-Q6_K.gguf"
    LLM_DUMMY_KEY: str = "sk-no-key-required"  # llama-server 무인증 — SDK 형식 충족용
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"
    LLM_TIMEOUT: float = 20.0


settings = Settings()


SCORE_TABLES = {
    "roe": [(-15, 0), (0, 5), (3, 10), (8, 15), (15, 20)],
    "operating_margin": [(-15, 0), (0, 5), (3, 10), (7, 15), (12, 20)],
    "debt_ratio": [(400, 0), (250, 5), (180, 10), (120, 15), (80, 20)],
    "current_ratio": [(50, 0), (100, 5), (130, 8), (180, 10)],
    "revenue_growth": [(-30, 0), (0, 4), (3, 8), (10, 12), (20, 15)],
    "operating_income_growth": [(-40, 0), (0, 4), (5, 8), (15, 12), (30, 15)],
}
