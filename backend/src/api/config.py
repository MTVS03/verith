"""애플리케이션 설정 (pydantic-settings).

이 브랜치 범위에서는 **DB 접속에 필요한 설정만** 둔다(통합 스키마 생성 전용).
API/AI 서버/JWT 등 나머지 설정은 각 담당자가 후속 브랜치에서 확장한다.

값의 정본은 환경변수 / `backend/.env` 이며, 코드에는 비밀값을 박지 않는다.
로컬 개발 편의를 위한 fallback DSN만 docker-compose 개발 자격(공개된 dev 값)으로 둔다.
"""

from __future__ import annotations

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 로컬 개발 fallback: docker-compose.yml 의 postgres(host 5433) + asyncpg 드라이버.
# 운영/CI 에서는 반드시 DATABASE_URL 환경변수로 주입한다.
_LOCAL_DEV_DATABASE_URL = "postgresql+asyncpg://verith:verith1234@localhost:5433/verith"


class Settings(BaseSettings):
    """환경변수/.env 기반 설정. 알 수 없는 키는 무시한다(다른 담당 영역 키 공존)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # SQLAlchemy async DSN. 비어 있으면 로컬 dev fallback 을 쓴다.
    DATABASE_URL: str = Field(default="")

    @model_validator(mode="after")
    def _fill_local_dev_dsn(self) -> "Settings":
        if not self.DATABASE_URL.strip():
            object.__setattr__(self, "DATABASE_URL", _LOCAL_DEV_DATABASE_URL)
        return self


settings = Settings()
