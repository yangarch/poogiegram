from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # 경로 (§4.1)
    media_root: Path = Path("/data/media")
    derived_root: Path = Path("/data/derived")
    storage_marker: str = ".poogiegram-ok"

    # 연결
    database_url: str
    redis_url: str = "redis://redis:6379/0"

    secret_key: str = "change-me"

    # 세션 (§8). 슬라이딩 만료라 쓰는 동안은 유지된다.
    session_ttl_days: int = 30
    # HTTPS 뒤에서만 True. 로컬 HTTP 개발 중에 True 면 쿠키가 아예 저장되지 않는다.
    cookie_secure: bool = False

    # 워커 전반의 동시 작업 수. 사진 디코딩은 CPU 병렬로 이득을 보므로
    # GPU 엔진 하나에 묶이는 트랜스코딩과 분리한다 (§6.3).
    worker_concurrency: int = 4

    # 트랜스코딩 (§6.3, §6.4)
    transcode_hwaccel: str = "auto"          # vaapi | none | auto
    transcode_concurrency: int = 2
    transcode_max_height: int = 1080

    # 인제스트 (§6.1)
    ingest_scan_interval_seconds: int = 300
    ingest_stable_seconds: int = 30

    @property
    def session_ttl_seconds(self) -> int:
        return self.session_ttl_days * 86400

    @property
    def originals_dir(self) -> Path:
        return self.media_root / "originals"

    @property
    def drop_dir(self) -> Path:
        """SFTP·웹 업로드가 파일을 넣는 곳 (§6.1)."""
        return self.media_root / "incoming" / "drop"

    @property
    def failed_dir(self) -> Path:
        return self.media_root / "incoming" / "failed"

    @property
    def tmp_dir(self) -> Path:
        """웹 업로드 청크 조립용. chroot 밖이라 SFTP 사용자에게 보이지 않는다."""
        return self.media_root / ".tmp"

    @property
    def trash_dir(self) -> Path:
        """소프트 삭제된 파일. asset.path 는 그대로 두고 루트만 바꿔 해석한다 (§5.3)."""
        return self.media_root / "trash"

    @property
    def marker_path(self) -> Path:
        return self.originals_dir / self.storage_marker


@lru_cache
def get_settings() -> Settings:
    return Settings()
