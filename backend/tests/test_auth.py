"""인증 검증 (§8).

세션·비밀번호·무차별 대입 억제. 인터넷에 노출될 로그인이라 동작을 확인해둔다.
"""

import time

import pytest

from poogiegram import auth


class FakeRedis:
    """세션 저장소 흉내. TTL 만료까지 재현한다."""

    def __init__(self):
        self.data: dict[str, tuple[str, float | None]] = {}

    def _live(self, key):
        v = self.data.get(key)
        if v is None:
            return None
        value, expires = v
        if expires is not None and expires < time.time():
            del self.data[key]
            return None
        return value

    async def set(self, key, value, ex=None):
        self.data[key] = (str(value), time.time() + ex if ex else None)

    async def get(self, key):
        return self._live(key)

    async def delete(self, *keys):
        for k in keys:
            self.data.pop(k, None)

    async def expire(self, key, ex):
        if (v := self._live(key)) is not None:
            self.data[key] = (v, time.time() + ex)

    async def incr(self, key):
        cur = int(self._live(key) or 0) + 1
        prev = self.data.get(key)
        self.data[key] = (str(cur), prev[1] if prev else None)
        return cur

    async def scan_iter(self, match=None, count=None):
        prefix = (match or "").rstrip("*")
        for k in list(self.data):
            if k.startswith(prefix):
                yield k


# ── 비밀번호 ────────────────────────────────────────────────────────


def test_해시는_매번_다르다():
    """같은 비밀번호라도 솔트가 달라 해시가 달라야 한다."""
    assert auth.hash_password("secret123") != auth.hash_password("secret123")


def test_검증():
    h = auth.hash_password("secret123")
    assert auth.verify_password(h, "secret123") is True
    assert auth.verify_password(h, "secret124") is False


def test_계정이_없어도_False_를_돌려준다():
    """None 을 넘겨도 예외가 아니라 False 여야 한다 — 호출부가 분기하지 않게."""
    assert auth.verify_password(None, "anything") is False


def test_계정_유무로_응답_시간이_갈리지_않는다():
    """존재하지 않는 계정도 같은 검증 비용을 치러야 한다.

    빠르게 실패하면 응답 시간만으로 어떤 아이디가 등록돼 있는지 알아낼 수 있다.
    """
    h = auth.hash_password("secret123")

    t0 = time.perf_counter(); auth.verify_password(h, "wrong"); real = time.perf_counter() - t0
    t0 = time.perf_counter(); auth.verify_password(None, "wrong"); missing = time.perf_counter() - t0

    assert missing > real * 0.3, "계정 없음 경로가 눈에 띄게 빠르면 안 된다"


# ── 세션 ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_세션_생성과_조회():
    r = FakeRedis()
    token = await auth.create_session(r, "user-1", 60)
    assert len(token) >= 32, "토큰이 추측 가능한 길이면 안 된다"
    assert await auth.read_session(r, token, 60) == "user-1"


@pytest.mark.asyncio
async def test_토큰이_없거나_틀리면_None():
    r = FakeRedis()
    assert await auth.read_session(r, "", 60) is None
    assert await auth.read_session(r, "made-up", 60) is None


@pytest.mark.asyncio
async def test_로그아웃하면_세션이_사라진다():
    r = FakeRedis()
    token = await auth.create_session(r, "user-1", 60)
    await auth.destroy_session(r, token)
    assert await auth.read_session(r, token, 60) is None


@pytest.mark.asyncio
async def test_만료된_세션은_무효():
    r = FakeRedis()
    token = await auth.create_session(r, "user-1", 1)
    r.data[f"{auth.SESSION_PREFIX}{token}"] = ("user-1", time.time() - 1)
    assert await auth.read_session(r, token, 60) is None


@pytest.mark.asyncio
async def test_사용하면_만료가_연장된다():
    """슬라이딩 만료 — 쓰는 동안은 로그인이 유지돼야 한다."""
    r = FakeRedis()
    token = await auth.create_session(r, "user-1", 10)
    before = r.data[f"{auth.SESSION_PREFIX}{token}"][1]
    await auth.read_session(r, token, 3600)
    assert r.data[f"{auth.SESSION_PREFIX}{token}"][1] > before


@pytest.mark.asyncio
async def test_계정의_모든_세션을_끊을_수_있다():
    """JWT 였다면 만료를 기다리거나 블랙리스트가 필요한 지점이다."""
    r = FakeRedis()
    a = await auth.create_session(r, "user-1", 60)
    b = await auth.create_session(r, "user-1", 60)
    other = await auth.create_session(r, "user-2", 60)

    assert await auth.destroy_all_sessions(r, "user-1") == 2
    assert await auth.read_session(r, a, 60) is None
    assert await auth.read_session(r, b, 60) is None
    assert await auth.read_session(r, other, 60) == "user-2", "다른 계정은 영향 없어야 한다"


# ── 무차별 대입 억제 ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_실패가_쌓이면_차단된다():
    r = FakeRedis()
    ip = "1.2.3.4"
    for _ in range(auth.MAX_LOGIN_FAILURES - 1):
        await auth.record_failure(r, ip)
    assert await auth.is_blocked(r, ip) is False

    await auth.record_failure(r, ip)
    assert await auth.is_blocked(r, ip) is True


@pytest.mark.asyncio
async def test_성공하면_실패_기록이_지워진다():
    r = FakeRedis()
    ip = "1.2.3.4"
    for _ in range(auth.MAX_LOGIN_FAILURES):
        await auth.record_failure(r, ip)
    await auth.clear_failures(r, ip)
    assert await auth.is_blocked(r, ip) is False


@pytest.mark.asyncio
async def test_차단은_IP별로_독립적이다():
    r = FakeRedis()
    for _ in range(auth.MAX_LOGIN_FAILURES):
        await auth.record_failure(r, "1.2.3.4")
    assert await auth.is_blocked(r, "1.2.3.4") is True
    assert await auth.is_blocked(r, "5.6.7.8") is False
