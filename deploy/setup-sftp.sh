#!/usr/bin/env bash
#
# SFTP 드롭 폴더 전용 계정을 만든다 (PROJECT.md §6.1).
#
# 이 계정은 incoming/ 안에 갇혀서 originals/ · trash/ · db/ 를 볼 수 없다.
# 셸 로그인도 불가하고 포트 포워딩·터널링도 막혀 있어, 설령 뚫려도
# 영향 범위가 드롭 폴더에 한정된다.
#
#   sudo ./deploy/setup-sftp.sh [계정명]
#
# 여러 번 실행해도 안전하다.

set -euo pipefail

USER_NAME="${1:-poogiedrop}"
GROUP_NAME="poogiegram"
MEDIA_ROOT="${MEDIA_ROOT:-/mnt/media}"
CHROOT="$MEDIA_ROOT/incoming"
SSHD_CONFIG="/etc/ssh/sshd_config"

die() { echo "오류: $*" >&2; exit 1; }
ok()  { echo "  ✓ $*"; }

[ "$(id -u)" -eq 0 ] || die "root 로 실행하세요:  sudo $0 $USER_NAME"

echo "== 1. 사전 점검 =="

getent group "$GROUP_NAME" >/dev/null \
  || die "$GROUP_NAME 그룹이 없습니다.  sudo groupadd -f $GROUP_NAME"
ok "$GROUP_NAME 그룹 존재 (gid $(getent group "$GROUP_NAME" | cut -d: -f3))"

[ -d "$CHROOT" ] || die "$CHROOT 가 없습니다. README 의 스토리지 준비 절차를 먼저 수행하세요."

# OpenSSH 는 ChrootDirectory 와 그 위 모든 상위 경로가 root 소유이고
# 그룹·타인 쓰기 권한이 없기를 요구한다. 어기면 접속이 그냥 끊기고
# 로그에만 "bad ownership or modes for chroot directory" 가 남는다.
check_path=""
IFS='/' read -ra parts <<< "${CHROOT#/}"
for part in "${parts[@]}"; do
    check_path="$check_path/$part"
    owner=$(stat -c '%U' "$check_path")
    mode=$(stat -c '%a' "$check_path")
    [ "$owner" = "root" ] \
      || die "$check_path 의 소유자가 $owner 입니다 (root 여야 함).  sudo chown root $check_path"
    # 그룹·타인 쓰기 비트가 있으면 안 된다
    if [ "$(( 8#$mode & 8#022 ))" -ne 0 ]; then
        die "$check_path 의 권한이 $mode 입니다 (그룹·타인 쓰기 불가).  sudo chmod 755 $check_path"
    fi
done
ok "chroot 경로 조건 충족 ($CHROOT 까지 root 소유, 그룹 쓰기 없음)"

# chroot 대상 자체에는 쓸 수 없으므로 안에 쓰기 가능한 하위 디렉터리가 필요하다.
for sub in drop failed; do
    d="$CHROOT/$sub"
    [ -d "$d" ] || die "$d 가 없습니다.  sudo mkdir -p $d"
    grp=$(stat -c '%G' "$d"); mode=$(stat -c '%a' "$d")
    [ "$grp" = "$GROUP_NAME" ] || die "$d 의 그룹이 $grp 입니다.  sudo chown root:$GROUP_NAME $d"
    # setgid(맨 앞 2)가 있어야 새 파일이 poogiegram 그룹을 상속한다.
    # 참고: chmod 775 같은 3자리 숫자 모드는 디렉터리의 setgid 를 지우지 않는다.
    # 실수로 지웠다면 chmod g-s 를 썼을 때다.
    [ "$mode" = "2775" ] || die "$d 의 권한이 $mode 입니다 (2775 필요).  sudo chmod 2775 $d"
done
ok "drop/ · failed/ 쓰기 가능, setgid 설정됨"

echo
echo "== 2. 계정 =="

if id "$USER_NAME" >/dev/null 2>&1; then
    ok "$USER_NAME 계정이 이미 있습니다"
else
    # 홈은 chroot 기준 경로다. 절대 경로를 넣으면 chroot 안에 그 경로가 없어
    # / 로 떨어진다. /drop 이면 접속 즉시 드롭 폴더에 들어간다.
    useradd -M -d /drop -s /usr/sbin/nologin -G "$GROUP_NAME" "$USER_NAME"
    ok "$USER_NAME 생성 (셸 없음, $GROUP_NAME 그룹)"
fi
usermod -aG "$GROUP_NAME" "$USER_NAME"

echo
echo "== 3. sshd 설정 =="

if grep -qE "^Match User $USER_NAME\$" "$SSHD_CONFIG"; then
    ok "sshd_config 에 이미 설정이 있습니다 (건드리지 않음)"
else
    cp "$SSHD_CONFIG" "$SSHD_CONFIG.bak-$(date +%F-%H%M)"
    ok "백업: $SSHD_CONFIG.bak-*"
    cat >> "$SSHD_CONFIG" <<CONF

# poogiegram 드롭 폴더 전용 (PROJECT.md §6.1)
Match User $USER_NAME
    ChrootDirectory $CHROOT
    ForceCommand internal-sftp -u 0002
    AllowTcpForwarding no
    PermitTunnel no
    X11Forwarding no
CONF
    ok "sshd_config 에 Match 블록 추가"
fi

sshd -t || die "sshd 설정에 오류가 있습니다. 위 메시지를 확인하세요. (백업본으로 되돌릴 수 있습니다)"
ok "sshd -t 통과"

echo
echo "== 4. 다음 할 일 =="
cat <<NEXT

  1) 비밀번호 또는 SSH 키를 설정하세요
       sudo passwd $USER_NAME

  2) 현재 SSH 세션을 열어둔 채로 sshd 를 재적용하세요.
     설정이 잘못돼도 열린 세션으로 되돌릴 수 있습니다.
       sudo systemctl reload sshd

  3) 다른 터미널에서 접속을 확인하세요
       sftp $USER_NAME@$(hostname)
       sftp> pwd     ← /drop 이어야 합니다
       sftp> ls /    ← drop 과 failed 만 보여야 합니다 (originals 가 보이면 안 됨)

  되돌리려면 $SSHD_CONFIG 의 'Match User $USER_NAME' 블록을 지우고
  sudo sshd -t && sudo systemctl reload sshd 를 실행하세요.
NEXT
