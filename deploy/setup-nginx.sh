#!/usr/bin/env bash
#
# 호스트 nginx 에 poogiegram 서버블록을 붙인다 (PROJECT.md §3.2).
#
# 새 리버스 프록시를 띄우지 않고 기존 nginx 를 재사용한다. 설정이 잘못되면
# **기존 사이트까지 함께 내려가므로** 단계마다 확인하고 nginx -t 통과 후에만 적용한다.
#
#   sudo ./deploy/setup-nginx.sh poogiegram.example.com
#
# 여러 번 실행해도 안전하다. TLS 는 마지막에 certbot 이 붙인다.

set -euo pipefail

DOMAIN="${1:-}"
API_PORT="${API_PORT:-8005}"
MEDIA_ROOT="${MEDIA_ROOT:-/mnt/media}"
DERIVED_ROOT="${DERIVED_ROOT:-/var/lib/poogiegram/derived}"
GROUP_NAME="poogiegram"
SITE="/etc/nginx/sites-available/poogiegram.conf"
ENABLED="/etc/nginx/sites-enabled/poogiegram.conf"

die() { echo "오류: $*" >&2; exit 1; }
ok()  { echo "  ✓ $*"; }
warn(){ echo "  ! $*"; }

[ -n "$DOMAIN" ] || die "도메인을 지정하세요:  sudo $0 poogiegram.example.com"
[ "$(id -u)" -eq 0 ] || die "root 로 실행하세요:  sudo $0 $DOMAIN"

echo "== 1. 사전 점검 =="

command -v nginx >/dev/null || die "nginx 가 설치돼 있지 않습니다."
nginx -t >/dev/null 2>&1 || die "기존 nginx 설정에 이미 오류가 있습니다. 먼저 해결하세요:  sudo nginx -t"
ok "기존 nginx 설정 정상"

# 앱이 응답하는지. 이게 안 되면 프록시를 붙여도 502 만 본다.
curl -fsS --max-time 5 "http://127.0.0.1:$API_PORT/healthz" >/dev/null \
  || die "127.0.0.1:$API_PORT 에서 앱이 응답하지 않습니다.  make up 으로 먼저 띄우세요."
ok "앱 응답 확인 (127.0.0.1:$API_PORT)"

# DNS. certbot 의 HTTP-01 인증은 이 도메인이 이 서버를 가리켜야 성공한다.
resolved=$(getent hosts "$DOMAIN" | awk '{print $1}' | head -1 || true)
public=$(curl -fsS --max-time 5 https://api.ipify.org 2>/dev/null || true)
if [ -z "$resolved" ]; then
    warn "$DOMAIN 이 아직 해석되지 않습니다. A 레코드를 먼저 등록하세요."
    warn "TLS 발급은 건너뛰고 HTTP 설정만 적용합니다."
elif [ -n "$public" ] && [ "$resolved" != "$public" ]; then
    warn "$DOMAIN → $resolved 인데 이 서버의 공인 IP 는 $public 입니다."
    warn "전파 중일 수 있습니다. TLS 발급이 실패하면 잠시 후 certbot 만 다시 실행하세요."
else
    ok "DNS: $DOMAIN → $resolved"
fi

# nginx 는 www-data 로 동작한다. 미디어 파일을 읽지 못하면 사진이 403 으로 안 뜬다.
if getent group "$GROUP_NAME" >/dev/null; then
    if id -nG www-data 2>/dev/null | tr ' ' '\n' | grep -qx "$GROUP_NAME"; then
        ok "www-data 가 $GROUP_NAME 그룹에 속함"
    else
        usermod -aG "$GROUP_NAME" www-data
        ok "www-data 를 $GROUP_NAME 그룹에 추가 (nginx 재시작 후 적용)"
    fi
fi

# 이미 root 이므로 sudo 를 쓰지 않는다 — 최소 설치 환경에는 없을 수 있다.
as_www() {
    if command -v runuser >/dev/null; then runuser -u www-data -- "$@"
    else su -s /bin/sh www-data -c "$(printf '%q ' "$@")"; fi
}

sample=$(find "$DERIVED_ROOT" -type f -name '*.webp' 2>/dev/null | head -1 || true)
if [ -n "$sample" ]; then
    if as_www test -r "$sample"; then
        ok "www-data 가 파생물을 읽을 수 있음"
    else
        # a+rX 로 열지 않는다 — 서버의 다른 사용자·서비스까지 사진을 읽게 된다 (§3.3).
        # www-data 는 poogiegram 그룹에 속하므로 그룹 읽기만 열면 충분하다.
        die "www-data 가 $sample 을 읽지 못합니다. nginx 가 사진을 서빙할 수 없습니다.

       원인을 먼저 확인하세요 (상위 디렉터리 권한까지 한 번에 보입니다):
         namei -om $sample

       파일이 0600 이면 (권한 수정 이전에 만들어진 파생물):
         make fix-perms

       그룹이 $GROUP_NAME 이 아니면:
         sudo chgrp -R $GROUP_NAME $DERIVED_ROOT && make fix-perms"
    fi
else
    warn "파생물이 아직 없어 읽기 권한을 확인하지 못했습니다."
fi

echo
echo "== 2. 서버블록 =="

# TLS 없이 80 만 먼저 올린다. 인증서가 없는 상태에서 443 을 적으면 nginx -t 가 실패한다.
# certbot 이 이 블록에 443 과 인증서 경로를 채워 넣는다.
if [ -f "$SITE" ] && grep -q "ssl_certificate" "$SITE"; then
    ok "이미 TLS 가 설정된 서버블록이 있습니다 (덮어쓰지 않음)"
else
    [ -f "$SITE" ] && cp "$SITE" "$SITE.bak-$(date +%F-%H%M)" && ok "백업: $SITE.bak-*"
    cat > "$SITE" <<CONF
server {
    listen 80;
    listen [::]:80;
    server_name $DOMAIN;

    # 웹 업로드는 파일 하나당 요청 하나다 (§6.6). 그래서 이 값은 **가장 큰 파일
    # 하나**를 담을 수 있어야 한다. 스냅사진 원본이 80MB, 아이폰 4K 영상은 그 이상
    # 이라 넉넉히 잡는다. 넘으면 nginx 가 413 을 내고 앱 로그에는 아무것도 안 남는다.
    client_max_body_size 2g;

    location / {
        proxy_pass http://127.0.0.1:$API_PORT;
        proxy_http_version 1.1;
        proxy_set_header Host              \$host;
        proxy_set_header X-Real-IP         \$remote_addr;
        proxy_set_header X-Forwarded-For   \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;

        proxy_request_buffering off;
        proxy_read_timeout 300s;
    }

    # X-Accel-Redirect 내부 경로 (§3.2).
    #
    # internal 이 핵심이다. 브라우저가 이 경로로 직접 요청하면 404 가 되고,
    # FastAPI 가 권한 검사를 마친 뒤 헤더로 지시했을 때만 서빙된다.
    # 바이트 전송을 nginx 가 맡는 이유: Python 이 4K 영상을 스트리밍하면
    # 워커가 오래 점유되어 API 응답 전체가 밀린다 (§3).
    location /_media/ {
        internal;
        alias $MEDIA_ROOT/;
        add_header Cache-Control "private, max-age=31536000, immutable";
    }

    location /_derived/ {
        internal;
        alias $DERIVED_ROOT/;
        add_header Cache-Control "private, max-age=31536000, immutable";
    }

    access_log /var/log/nginx/poogiegram.access.log;
    error_log  /var/log/nginx/poogiegram.error.log;
}
CONF
    ok "서버블록 작성: $SITE"
fi

ln -sfn "$SITE" "$ENABLED"
ok "활성화: $ENABLED"

nginx -t || die "nginx 설정 오류. 위 메시지를 확인하세요. 적용하지 않았으므로 기존 사이트는 그대로입니다."
ok "nginx -t 통과"

systemctl reload nginx
ok "nginx 재적용 (기존 연결은 끊기지 않음)"

echo
echo "== 3. TLS =="

if grep -q "ssl_certificate" "$SITE"; then
    ok "인증서가 이미 설정돼 있습니다"
elif [ -z "$resolved" ]; then
    warn "DNS 미설정으로 건너뜁니다. A 레코드 등록 후 아래를 실행하세요:"
    echo "       sudo certbot --nginx -d $DOMAIN"
elif ! command -v certbot >/dev/null; then
    warn "certbot 이 없습니다. 설치 후 아래를 실행하세요:"
    echo "       sudo certbot --nginx -d $DOMAIN"
else
    certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --register-unsafely-without-email \
      || warn "certbot 실패. DNS 전파를 기다린 뒤 다시 시도하세요:  sudo certbot --nginx -d $DOMAIN"
fi

echo
echo "== 4. 다음 할 일 =="
cat <<NEXT

  HTTPS 로 서비스하므로 쿠키에 Secure 를 켜야 합니다.
    .env 에서  COOKIE_SECURE=true  로 바꾸고  make up

  (HTTP 로 접속하는 동안 true 로 두면 브라우저가 쿠키를 저장하지 않아
   로그인이 계속 풀립니다. TLS 가 붙은 뒤에 바꾸세요.)

  확인:
    curl -I https://$DOMAIN/
    브라우저에서 https://$DOMAIN/

  문제가 생기면:
    sudo tail -f /var/log/nginx/poogiegram.error.log
    사진만 안 보이면 www-data 읽기 권한 문제일 가능성이 높습니다.
NEXT
