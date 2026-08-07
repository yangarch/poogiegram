FROM python:3.12-slim-bookworm

# ffmpeg (bookworm = 5.1.x, Ubuntu 22.04 의 4.4 보다 톤매핑·VAAPI 수정이 많이 들어가 있다)
# intel-media-va-driver-non-free 는 non-free 컴포넌트에 있다 — HEVC 인코드가 여기 들어 있다 (§6.4)
RUN set -eux; \
    echo 'deb http://deb.debian.org/debian bookworm non-free non-free-firmware' \
        > /etc/apt/sources.list.d/non-free.list; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        ffmpeg \
        libva2 libva-drm2 vainfo \
        intel-media-va-driver-non-free \
        libimage-exiftool-perl \
        libheif1 \
        curl \
    ; \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY poogiegram ./poogiegram

# 비루트로 실행. worker 는 compose 에서 group_add 로 render 그룹을 추가로 받는다.
RUN useradd --create-home --uid 10001 app && chown -R app:app /app
USER app

EXPOSE 8005
