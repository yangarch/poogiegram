"""로깅 설정.

arq 는 자기 로거(`arq.*`)만 설정한다. 우리 로거는 루트를 상속해 기본이 WARNING 이라,
설정하지 않으면 **인제스트 로그가 하나도 보이지 않는다.** 실제로 그렇게 만들어놓고
"스캐너가 안 도는 줄" 알았던 적이 있어 이 모듈을 둔다.
"""

from __future__ import annotations

import logging
import os


def setup(name: str = "poogiegram") -> None:
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # arq 나 uvicorn 이 이미 루트 핸들러를 붙였다면 그걸 쓴다.
    # 없을 때만 붙여서 같은 줄이 두 번 찍히는 것을 막는다.
    if not logging.getLogger().handlers and not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logger.addHandler(handler)
