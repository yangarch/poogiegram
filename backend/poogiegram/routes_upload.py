"""웹 업로드 (§6.6).

아이폰에서 사진을 넣을 방법이 이것뿐이다. SFTP 는 맥에서만 되고, 그러면 결국
"남편에게 부탁해서 넣기"가 되어 아무도 안 쓰게 된다.

**드롭 폴더에 파일을 놓는 것까지만 한다.** 해시·메타데이터·파생물은 전부 기존
인제스트가 맡는다 (§6.1). HTTP 요청 안에서 그 일을 하면 타임아웃이 나고 워커가
점유되어 API 전체가 밀린다.

태그도 마찬가지로 기존 경로를 쓴다 — 고른 태그 이름으로 드롭 폴더 안에 폴더를
만들면 폴더→태그 규칙(§5.5)이 그대로 적용된다. 새 경로를 만들지 않는 편이
검증된 동작을 재사용하는 길이다.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status

from .deps import current_user
from .ingest.pipeline import TAG_NAME_MAX

log = logging.getLogger("poogiegram.upload")

router = APIRouter(prefix="/api/upload", tags=["upload"], dependencies=[Depends(current_user)])

# 한 번에 읽어 쓰는 크기. 통째로 메모리에 올리면 큰 영상에서 워커가 죽는다.
CHUNK = 1024 * 1024

# 경로로 해석될 수 있는 문자를 전부 막는다. 태그 이름은 사용자가 정하는 값이라
# 그대로 디렉터리 이름으로 쓰면 ../ 로 드롭 폴더 밖에 쓸 수 있다.
_UNSAFE = re.compile(r'[/\\:*?"<>|\x00-\x1f]')


def safe_component(name: str, fallback: str) -> str:
    """파일·디렉터리 이름으로 써도 안전한 문자열로 만든다.

    맥과 아이폰이 한글을 NFD(자모 분리)로 보내는 경우가 있어 NFC 로 모은다.
    그대로 두면 같은 "결혼기념일"이 다른 폴더로 갈라진다.
    """
    name = unicodedata.normalize("NFC", name)
    name = _UNSAFE.sub("_", name).strip().strip(".")
    name = " ".join(name.split())
    return name[:TAG_NAME_MAX] or fallback


@router.post("")
async def upload(
    request: Request,
    file: UploadFile = File(...),
    tag: str | None = Form(None),
) -> dict:
    """파일 하나를 드롭 폴더에 놓는다.

    파일 하나당 요청 하나다. 여러 개를 한 요청에 묶으면 하나가 실패했을 때
    무엇이 들어갔는지 알 수 없고, 진행률도 파일 단위로 못 보여준다.
    """
    settings = request.app.state.settings

    target_dir = settings.drop_dir
    if tag and (folder := safe_component(tag, "")):
        target_dir = target_dir / folder
    target_dir.mkdir(parents=True, exist_ok=True)

    filename = safe_component(file.filename or "", "upload")
    dest = target_dir / filename

    # 같은 이름이 이미 대기 중이면 덮어쓰지 않는다. 내용이 같으면 인제스트가
    # 해시로 중복을 걸러내므로, 여기서는 일단 받아두는 편이 안전하다.
    stem, dot, suffix = filename.partition(".")
    counter = 1
    while dest.exists():
        dest = target_dir / f"{stem}_{counter}{dot}{suffix}"
        counter += 1

    # .partial 로 쓰고 다 받은 뒤 rename 한다. 스캐너가 이 확장자를 무시하므로
    # (scanner._IGNORED_SUFFIXES) 전송 중인 파일을 잘린 채로 집어가지 않는다.
    tmp = dest.with_name(dest.name + ".partial")
    size = 0
    try:
        with tmp.open("wb") as out:
            while data := await file.read(CHUNK):
                out.write(data)
                size += len(data)
        if size == 0:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "빈 파일입니다")
        tmp.replace(dest)
    except HTTPException:
        tmp.unlink(missing_ok=True)
        raise
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        log.error("업로드 저장 실패: %s — %s", filename, exc)
        raise HTTPException(
            status.HTTP_507_INSUFFICIENT_STORAGE, "서버에 저장하지 못했습니다"
        ) from exc

    log.info("업로드 수신: %s (%d bytes)%s", dest.name, size, f" 태그={tag}" if tag else "")

    # 스캔을 앞당긴다. 주기 스캔은 300초라 그때까지 화면에 아무 변화가 없다.
    # 안정성 검사(30초)는 그대로 거치므로 잘린 파일이 들어갈 위험은 없다 (§6.1).
    await request.app.state.arq.enqueue_job("scan_drop_folder")

    return {"filename": dest.name, "bytes": size}
