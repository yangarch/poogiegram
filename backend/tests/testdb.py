"""운영 DATABASE_URL 에서 **테스트 전용 DB** URL 을 만든다.

DB 를 쓰는 테스트는 asset 테이블을 비운다. 운영 DB 를 가리킨 채 돌리면 사진이
전부 사라진다 — 실제로 그렇게 날렸다. 서버·계정은 그대로 두고 데이터베이스
이름만 분리해서, 지우더라도 운영 데이터에 닿지 않게 한다.

make test-db 가 쓴다. pytest 가 수집하지 않도록 파일명은 test_ 로 시작하지 않는다.
"""

import os
import sys
from urllib.parse import urlsplit, urlunsplit

SUFFIX = "_test"


def db_name(url: str) -> str:
    return (urlsplit(url).path.lstrip("/") or "poogiegram") + SUFFIX


def db_url(url: str) -> str:
    return urlunsplit(urlsplit(url)._replace(path=f"/{db_name(url)}"))


if __name__ == "__main__":
    source = os.environ.get("DATABASE_URL")
    if not source:
        sys.exit("DATABASE_URL 이 없습니다")
    print(db_name(source) if "--name" in sys.argv else db_url(source))
