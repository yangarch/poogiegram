"""컬럼에 들어가는 값 집합.

PostgreSQL ENUM 타입 대신 **text + CHECK 제약**을 쓴다. ENUM 은 값 하나를 추가하는 데도
`ALTER TYPE` 이 필요하고 트랜잭션 안에서 제약이 있어 마이그레이션이 번거롭다.
CHECK 는 제약을 지우고 다시 거는 것으로 끝난다.
"""

KIND = ("image", "video")

# 촬영일을 어디서 얻었는지 (§6.7).
# 'mtime' 과 'unknown' 은 신뢰도가 낮아 "과거의 오늘"에서 제외한다 (§5.1).
DATE_SOURCE = ("exif", "xmp", "filename", "sibling", "mtime", "manual", "unknown")

# 사진·영상 공통. HEIC 는 파생물이 생기기 전까지 크롬에서 아예 안 보이므로
# "원본은 있는데 화면엔 안 뜨는" 상태를 UI 가 구분할 수 있어야 한다 (§5).
DERIVE_STATUS = ("pending", "ready", "failed")

# 영상 전용. 'direct' = 변환 없이 Range 로 서빙 가능 (§6.3).
VIDEO_STATUS = ("direct", "needs_transcode", "ready", "failed")

USER_ROLE = ("admin", "member")

# 인제스트 이력 (§5.2). 큐 상태가 아니라 "무엇이 언제 어떻게 됐는지" 기록.
INGEST_EVENT = ("ingested", "duplicate", "restored", "failed")

ROTATION = (0, 90, 180, 270)


def sql_in(values: tuple) -> str:
    """CHECK 제약에 쓸 IN 목록을 만든다."""
    return ", ".join(f"'{v}'" if isinstance(v, str) else str(v) for v in values)
