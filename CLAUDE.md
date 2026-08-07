# poogiegram — 작업 규칙

개인 미디어 라이브러리 서버. 설계 근거는 전부 `PROJECT.md`에 있고, **결정이 바뀌면
PROJECT.md부터 고친다.** 이 파일은 코드를 쓸 때 반복해서 필요한 것만 담는다.

## 절대 어기면 안 되는 것

이 다섯 가지는 어기면 **데이터를 잃거나 조용히 망가진다.**

1. **원본의 내용을 변경하지 않는다.** `originals/` 아래 파일은 읽기만 한다.
   회전·날짜 수정은 DB와 파생물에 반영하고 원본은 그대로 둔다.
   예외는 **위치 이동뿐**이다 — 촬영일이 확정되면 `_undated/`에서 날짜 경로로 옮긴다
   (§4.1, §6.7). 이때도 내용은 건드리지 않는다.

2. **바이트를 Python으로 흘려보내지 않는다.** 파일 응답은 권한 검사 후
   `X-Accel-Redirect` 헤더만 반환한다. 실제 전송은 nginx가 한다 (§3).
   `FileResponse`/`StreamingResponse`로 미디어를 내보내는 코드를 쓰지 않는다.

3. **기동 전에 마운트를 확인한다.** `originals/.poogiegram-ok`가 없으면 기동을 거부한다
   (§4.6). `nofail` 마운트라 디스크가 없어도 부팅은 되고, 그 상태로 앱이 뜨면
   빈 마운트 포인트에 원본을 쓴다.

4. **PostgreSQL·Redis를 호스트에 노출하지 않는다.** compose에 `ports:`를 추가하지 않는다 (§3.1).

5. **영상 필터 체인에 `format=nv12`를 반드시 넣는다.** 아이폰 HEVC는 10bit이고
   이 하드웨어의 H.264 인코드는 8bit 전용이라, 빠뜨리면
   `No usable encoding profile found`로 **모든 영상 변환이 실패한다** (§6.3).

## 자주 틀리는 지점

- **`taken_local` vs `taken_at`** — 날짜 그룹핑·추억은 `taken_local`(현지), 정렬은 `taken_at`(절대).
  `EXTRACT(MONTH FROM timestamptz)`는 IMMUTABLE이 아니라 인덱스를 못 탄다 (§5).
- **타임라인 쿼리에 `is_live_motion = false`** — 빠뜨리면 라이브 포토 MOV가 목록에 샌다.
- **`-low_power`는 런타임 탐지로 결정** — 하드코딩하지 않는다. `EncSlice`가 있으면 붙이지
  않고, `EncSliceLP`만 있으면 붙여야 한다 (§6.4).
- **소프트 삭제 시 `path`를 바꾸지 않는다** — `deleted_at` 유무로 루트만 다르게 해석한다 (§5.3).
- **인제스트는 30초 안정성 검사를 거친다** — 업로드 중인 파일을 잘린 채로 집어가지 않기 위해서다 (§6.1).

## 명령

```bash
make up          # 전체 기동 (/dev/dri 있으면 VA-API 오버레이 자동 적용)
make status      # 헬스체크
make logs S=api  # 로그
make psql        # DB 접속
make vainfo      # 워커 컨테이너에서 VA-API 확인
make dump        # pg_dump → /mnt/media/db/
```

## 환경

- 서버: Intel 8세대(Coffee Lake) 6코어 / 16GB / Ubuntu. 호스트 nginx가 80·443 사용 중
- 스토리지: `/mnt/media`(원본·드롭·DB덤프)는 외장 HDD, `derived/`는 내장 NVMe
- GPU: HEVC 10bit 디코드 + H.264 VME 인코드. **`i915.enable_guc=2` 필수** (§6.4)
- API는 8005, 호스트에 127.0.0.1로만 바인딩

**실제 호스트명·계정·디스크 UUID·다른 서비스의 포트는 `docs/environment.local.md`에 있다**
(커밋하지 않는 파일). 공개 저장소에는 설계와 근거만 남긴다.

## 코드

- Python 3.12, FastAPI + SQLAlchemy 2.0(async) + arq
- 주석은 **왜**를 적는다. 무엇을 하는지는 코드가 말한다.
- 첫 빌드가 성공하면 `pip freeze > requirements.lock`으로 버전을 잠근다
  (현재 `requirements.txt`는 하한만 지정).
