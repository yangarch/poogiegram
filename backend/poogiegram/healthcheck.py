"""Docker HEALTHCHECK 진입점.

curl 대신 이 모듈을 쓰는 이유는 종료 코드와 함께 실패 원인을 로그에 남기기 위해서다.
    python -m poogiegram.healthcheck
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

URL = "http://127.0.0.1:8005/readyz"
TIMEOUT = 5


def main() -> int:
    try:
        with urllib.request.urlopen(URL, timeout=TIMEOUT) as resp:  # noqa: S310 — 루프백 고정
            body = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        print(f"readyz {exc.code}: {exc.read().decode(errors='replace')}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"readyz 도달 실패: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    if body.get("status") != "ok":
        print(f"readyz 비정상: {body}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
