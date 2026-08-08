"""Docker HEALTHCHECK 진입점.

    python -m poogiegram.healthcheck            # /healthz — 라이브니스 (기본)
    python -m poogiegram.healthcheck --ready    # /readyz  — 의존성까지 확인

**Docker 헬스체크는 라이브니스를 본다.** "프로세스가 트래픽을 받을 수 있는가"이지
"모든 운영 준비가 끝났는가"가 아니다. readyz 는 마이그레이션 적용까지 확인하는데,
그걸 헬스체크로 쓰면 신규 설치에서 닭과 달걀이 된다 — 마이그레이션은 컨테이너가
떠야 실행할 수 있는데 컨테이너는 마이그레이션이 돼야 healthy 가 되기 때문이다.

curl 대신 이 모듈을 쓰는 이유는 종료 코드와 함께 실패 원인을 로그에 남기기 위해서다.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8005"
TIMEOUT = 5


def main() -> int:
    ready = "--ready" in sys.argv
    url = f"{BASE}/readyz" if ready else f"{BASE}/healthz"
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as resp:  # noqa: S310 — 루프백 고정
            body = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        print(f"{url} {exc.code}: {exc.read().decode(errors='replace')}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"{url} 도달 실패: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    if body.get("status") != "ok":
        print(f"{url} 비정상: {body}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
