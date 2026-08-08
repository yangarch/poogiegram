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

**2. 환경 설정**

```bash
cp .env.example .env
openssl rand -hex 32                    # SECRET_KEY 에 넣는다
getent group render | cut -d: -f3       # RENDER_GID 에 넣는다
```

`RENDER_GID`가 틀리면 컨테이너 안에서만 GPU 접근이 `Permission denied`로 막히고
호스트에서는 정상 동작해서 원인을 찾기 어렵다.

**3. 기동**

```bash
make up
make migrate     # DB 스키마 적용 (최초 1회, 이후 스키마 변경 시)
make status
```

`readyz` 의 `database` 항목에 `ok (migration 0001)` 처럼 리비전이 함께 표시된다 —
연결만 되고 스키마가 없는 상태를 구분하기 위해서다.

`/dev/dri`가 있으면 VA-API 오버레이가 자동으로 적용된다.

**4. nginx (외부 접속이 필요할 때)**

```bash
sudo cp deploy/nginx/poogiegram.conf.example /etc/nginx/sites-available/poogiegram.conf
# server_name 을 실제 도메인으로 수정
sudo ln -s /etc/nginx/sites-available/poogiegram.conf /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

## 확인

```bash
make status                       # 스토리지·DB·Redis 상태
make vainfo                       # 컨테이너에서 VA-API 가 보이는지
curl -s localhost:8005/readyz     # 상세 체크 결과
```

## 진행 상황

| 단계 | 내용 | 상태 |
|---|---|---|
| M0 | 저장소·Compose 골격, 헬스체크 | ✅ 완료 |
| M1 | 드롭 폴더 인제스트 + HEIC 변환 + 썸네일 | **진행 중** |
| M2 | 인증 + 타임라인 + 라이트박스 | |
| M3 | 동영상 (HEVC → HLS, 톤매핑) | |
| M4 | 앨범·태그·검색 | |
| M5 | 웹 업로드, 공유 링크, 휴지통 | |
