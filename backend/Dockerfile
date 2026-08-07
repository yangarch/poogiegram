FROM python:3.12-slim-bookworm

# ffmpeg (bookworm = 5.1.x, Ubuntu 22.04 의 4.4 보다 톤매핑·VAAPI 수정이 많이 들어가 있다)
#
# non-free 컴포넌트 활성화가 필요하다 — intel-media-va-driver-non-free 가 거기 있고,
# 그 안에 HEVC 인코드 커널이 들어 있다 (§6.4).
#
# bookworm 이미지는 deb822 형식(/etc/apt/sources.list.d/debian.sources)을 쓴다.
# 구형 한 줄 형식으로 같은 URI·suite 를 다시 선언하면 Signed-By 값이 충돌해
# `E: Conflicting values set for option Signed-By` 로 apt-get update 가 실패한다.
# 그래서 새 소스를 추가하지 않고 기존 파일의 Components 를 확장한다.
RUN set -eux; \
    if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
        sed -i 's/^Components: .*/& contrib non-free non-free-firmware/' \
            /etc/apt/sources.list.d/debian.sources; \
    else \
        echo 'deb [signed-by=/usr/share/keyrings/debian-archive-keyring.gpg]' \
             'http://deb.debian.org/debian bookworm contrib non-free non-free-firmware' \
            > /etc/apt/sources.list.d/non-free.list; \
    fi; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        ffmpeg \
        libva2 libva-drm2 vainfo \
        libimage-exiftool-perl \
        libheif1 \
        curl \
    ; \
    # 인텔 VA-API 드라이버는 amd64 전용이다. arm64(맥)에서도 이미지가 빌드되도록 분기한다 —
    # 하드웨어 가속은 리눅스 서버에서만 쓰고, arm64 빌드는 개발·검증용이다.
    if [ "$(dpkg --print-architecture)" = "amd64" ]; then \
        apt-get install -y --no-install-recommends intel-media-va-driver-non-free; \
    fi; \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# requirements.lock 은 검증된 빌드에서 뽑은 전체 잠금이다 (전이 의존성 포함).
# requirements.txt 는 직접 의존성 목록으로 남겨두고, 실제 설치는 lock 으로 한다.
COPY requirements.txt requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock

COPY poogiegram ./poogiegram

# 비루트로 실행. worker 는 compose 에서 group_add 로 render 그룹을 추가로 받는다.
RUN useradd --create-home --uid 10001 app && chown -R app:app /app
USER app

EXPOSE 8005
