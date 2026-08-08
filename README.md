# poogiegram

개인 미디어 라이브러리 서버. 사진·동영상을 자체 서버에 보관하고 웹 브라우저로 열람한다.

설계 문서: **[PROJECT.md](PROJECT.md)** · 작업 규칙: [CLAUDE.md](CLAUDE.md)

> 이 저장소에는 **설계와 그 근거**만 담는다. 실제 호스트명·계정·디스크 UUID·포트 점유
> 현황 같은 환경 값은 `docs/environment.local.md`(커밋하지 않음)에 둔다.

## 구성

```
브라우저 ──443──▶ 호스트 nginx ──▶ FastAPI(:8005) ──▶ PostgreSQL / Redis
                      │                                      │
                      │ X-Accel-Redirect                  arq worker
                      ▼                                      │
              /mnt/media · derived/  ◀──────────────── ffmpeg / VA-API
```

권한 검사는 FastAPI가 하고 **파일 전송은 nginx가 직접 한다.** Python이 대용량 파일을
스트리밍하면 워커가 점유되어 API 응답 전체가 밀리기 때문이다.

## 요구 사항

- Docker + Docker Compose
- 리눅스 호스트 (하드웨어 트랜스코딩에 `/dev/dri` 필요)
- 호스트 nginx (80/443)
- `i915.enable_guc=2` — HuC 펌웨어가 없으면 인코드 엔트리포인트가 반쪽만 노출된다

## 시작하기

**1. 스토리지 준비**

```bash
sudo mkdir -p /mnt/media/{originals,trash,db,.tmp} /mnt/media/incoming/{drop,failed}
sudo mkdir -p /var/lib/poogiegram/derived
sudo touch /mnt/media/originals/.poogiegram-ok
```

마커 파일이 없으면 앱이 기동을 거부한다. 외장 디스크가 마운트되지 않은 채로 떠서
빈 디렉터리에 원본을 쌓는 사고를 막기 위한 것이다.

**2. 공용 그룹과 권한**

업로드하는 사람과 컨테이너 안의 워커가 같은 파일을 다뤄야 한다. 공용 그룹으로 묶는다.

```bash
sudo groupadd -f poogiegram
sudo usermod -aG poogiegram $USER          # 업로드할 계정
sudo chown -R root:poogiegram /mnt/media /var/lib/poogiegram
sudo chmod 2775 /mnt/media/{originals,trash,db,.tmp} /mnt/media/incoming/{drop,failed}
sudo chmod 2775 /var/lib/poogiegram /var/lib/poogiegram/derived
sudo chmod 755  /mnt/media /mnt/media/incoming
```

`derived/` 를 빠뜨리면 인제스트는 되는데 **파생물만 전부 실패한다** — HEIC 는
파생물이 없으면 화면에 아무것도 안 보이므로 증상이 "사진이 안 보인다"로 나타난다.

`2775` 의 setgid 비트가 핵심이다 — 새로 만들어지는 파일이 `poogiegram` 그룹을 상속해서,
올린 사람과 워커가 같은 그룹으로 접근하게 된다.
`/mnt/media` 와 `incoming` 을 `755` 로 두는 것은 SFTP chroot 조건 때문이다
(chroot 대상과 그 상위 경로는 root 소유에 그룹 쓰기 권한이 없어야 한다).

**그룹 추가는 새 세션부터 적용된다** — SSH·SFTP 를 끊고 다시 접속해야 한다.

**3. 환경 설정**

```bash
cp .env.example .env
openssl rand -hex 32                    # SECRET_KEY 에 넣는다
getent group render | cut -d: -f3       # RENDER_GID 에 넣는다
```

`RENDER_GID`가 틀리면 컨테이너 안에서만 GPU 접근이 `Permission denied`로 막히고
호스트에서는 정상 동작해서 원인을 찾기 어렵다.

**4. 기동**

```bash
make up          # 빌드 → 기동 → 마이그레이션 → 상태 확인까지 한 번에
```

`readyz` 의 `database` 항목에 `ok (migration 0001)` 처럼 리비전이 함께 표시된다 —
연결만 되고 스키마가 없는 상태를 구분하기 위해서다.

`/dev/dri`가 있으면 VA-API 오버레이가 자동으로 적용된다.

**5. SFTP 드롭 계정 (선택)**

관리 계정으로 올리면 `originals/` 까지 보이고 지울 수도 있다.
전용 계정을 만들어 드롭 폴더에 가둔다.

```bash
sudo ./deploy/setup-sftp.sh          # 계정명 기본값 poogiedrop
```

스크립트가 chroot 조건(경로 소유·권한, setgid)을 먼저 점검하고 문제가 있으면
고칠 명령과 함께 멈춘다. 여러 번 실행해도 안전하다.
**sshd 재적용은 기존 SSH 세션을 열어둔 채로** 하는 것을 권한다.

**6. nginx + TLS (외부 접속이 필요할 때)**

```bash
sudo ./deploy/setup-nginx.sh poogiegram.example.com
```

기존 nginx 를 재사용한다. 설정이 잘못되면 **기존 사이트까지 함께 내려가므로**
스크립트가 먼저 점검하고 `nginx -t` 통과 후에만 적용한다:

- 기존 nginx 설정이 이미 정상인지
- 앱이 `127.0.0.1:8005` 에서 응답하는지 (아니면 502 만 보게 된다)
- DNS 가 이 서버를 가리키는지 (certbot 의 HTTP-01 인증 조건)
- **`www-data` 가 미디어 파일을 읽을 수 있는지** — 아니면 화면은 뜨는데 사진만 안 보인다

TLS 는 certbot 이 붙인다. 끝나면 `.env` 의 `COOKIE_SECURE=true` 로 바꾸고 `make up`.
HTTP 로 접속하는 동안 `true` 면 브라우저가 쿠키를 저장하지 않아 로그인이 계속 풀린다.

## 개발

프런트엔드만 따로 고칠 때는 Vite 개발 서버를 쓴다. `/api` 는 백엔드로 넘어간다.

```bash
cd web && npm install && npm run dev     # http://localhost:5173
```

빌드 산출물은 이미지에 함께 들어가므로 배포 시 별도 작업이 없다.

## 확인

```bash
make status                       # 스토리지·DB·Redis 상태
make vainfo                       # 컨테이너에서 VA-API 가 보이는지
curl -s localhost:8005/readyz     # 상세 체크 결과

# 인제스트 (§6.1)
curl -s localhost:8005/api/ingest/status   # 대기·완료·실패 건수
curl -sXPOST localhost:8005/api/ingest/scan  # 주기 스캔을 기다리지 않고 즉시
```

## 진행 상황

| 단계 | 내용 | 상태 |
|---|---|---|
| M0 | 저장소·Compose 골격, 헬스체크 | ✅ 완료 |
| M1 | 드롭 폴더 인제스트 + HEIC 변환 + 썸네일 | ✅ 완료 |
| M2 | 인증 + 타임라인 + 라이트박스 | **진행 중** — 인증·서빙·그리드 완료, 라이트박스 남음 |
| M3 | 동영상 (HEVC → HLS, 톤매핑) | |
| M4 | 앨범·태그·검색 | |
| M5 | 웹 업로드, 공유 링크, 휴지통 | |
