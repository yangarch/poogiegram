"""SPA 폴백이 API·헬스체크를 삼키지 않는지 (§3).

SPA 폴백 `/{path:path}` 는 **모든 경로에 매칭된다.** FastAPI 는 등록 순서대로
매칭하므로, 이 라우트가 먼저 등록되면 뒤에 정의된 라우트가 전부 삼켜진다.

실제로 이 일이 있었다: 프런트엔드를 붙인 뒤 `/healthz` 가 index.html 을 200 으로
돌려주었고, 헬스체크가 JSON 파싱에 실패해 컨테이너가 unhealthy 로 떨어졌다.
앱 로그에는 `GET /healthz 200 OK` 만 찍혀서 원인이 한눈에 보이지 않았다.

**응답을 검사한다.** 처음에는 app.routes 를 훑어 등록 순서를 봤는데, 이 버전의
FastAPI 는 include_router 로 넣은 라우트를 _IncludedRouter 로 감싸 두어서 그 안이
보이지 않았다. 내부 구조는 버전에 따라 바뀌지만 "헬스체크는 JSON 을 준다"는
계약은 그대로다. 깨진 것도 그 계약이었다.

lifespan 을 돌리지 않으므로 DB·Redis 가 없어도 된다 — TestClient 를 with 없이
쓰면 기동 이벤트가 실행되지 않는다.
"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from poogiegram.main import create_app


def _client(app) -> TestClient:
    # 인증 의존성이 상태를 먼저 건드린다. 빈 쿠키로 401 까지만 가면 되므로
    # 최소한만 채운다 — 여기서 500 이 나면 "폴백에 안 삼켜졌다"는 신호가 흐려진다.
    app.state.redis = None
    app.state.settings = SimpleNamespace(session_ttl_seconds=0)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def with_static(tmp_path):
    """빌드 산출물이 있는 상태. 이때만 폴백이 붙는다."""
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<!doctype html><title>poogiegram</title>")
    return _client(create_app(static_dir=static))


@pytest.fixture
def without_static(tmp_path):
    """개발 모드. Vite 가 프런트를 담당하고 앱은 API 만 낸다."""
    return _client(create_app(static_dir=tmp_path / "없음"))


def test_spa_폴백이_실제로_붙는다(with_static):
    """폴백이 없으면 아래 테스트들이 전부 무의미하게 통과한다."""
    res = with_static.get("/타임라인/2024")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]


def test_healthz는_json을_돌려준다(with_static):
    """이게 깨져서 컨테이너가 unhealthy 로 떨어졌다."""
    res = with_static.get("/healthz")
    assert res.status_code == 200, res.text
    assert res.json() == {"status": "ok"}


def test_readyz는_html이_아니다(with_static):
    """의존성이 없어 내용은 실패하지만, index.html 이 돌아오면 안 된다.

    lifespan 을 돌리지 않아 app.state 가 비어 있으므로 500 이 정상이다.
    확인하려는 것은 상태 코드가 아니라 **폴백에 삼켜지지 않았다는 사실**이다.
    """
    res = with_static.get("/readyz")
    assert "text/html" not in res.headers.get("content-type", ""), "폴백이 삼켰다"


def test_api는_폴백에_삼켜지지_않는다(with_static):
    """인증이 걸린 API 는 401 이어야 한다. 200 + HTML 이면 폴백이 가로챈 것이다."""
    res = with_static.get("/api/assets")
    assert res.status_code == 401, res.text


def test_없는_api는_404다(with_static):
    """index.html 이 200 으로 돌아가면 디버깅이 헷갈린다."""
    res = with_static.get("/api/없는경로")
    assert res.status_code == 404
    assert "text/html" not in res.headers.get("content-type", "")


def test_static이_없어도_api는_동작한다(without_static):
    assert without_static.get("/healthz").json() == {"status": "ok"}
    assert without_static.get("/api/assets").status_code == 401


def test_static이_없으면_폴백을_붙이지_않는다(without_static):
    assert without_static.get("/타임라인/2024").status_code == 404
