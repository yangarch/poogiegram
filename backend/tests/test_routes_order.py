"""라우트 등록 순서 (§3).

SPA 폴백 `/{path:path}` 는 **모든 경로에 매칭된다.** FastAPI 는 등록 순서대로
매칭하므로, 이 라우트가 먼저 등록되면 뒤에 정의된 라우트가 전부 삼켜진다.

실제로 이 일이 있었다: 프런트엔드를 붙인 뒤 `/healthz` 가 index.html 을 200 으로
돌려주었고, 헬스체크가 JSON 파싱에 실패해 컨테이너가 unhealthy 로 떨어졌다.
앱 로그에는 `GET /healthz 200 OK` 만 찍혀서 원인이 한눈에 보이지 않았다.

static/ 이 없으면 폴백이 등록되지 않아 버그가 재현되지 않는다. 그래서 임시 경로에
빌드 산출물 흉내를 내고 create_app 에 넘긴다.
"""

import pytest

from poogiegram.main import create_app


@pytest.fixture
def app_with_static(tmp_path):
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<!doctype html><title>poogiegram</title>")
    return create_app(static_dir=static)


def _paths(app) -> list[str]:
    return [r.path for r in app.routes if hasattr(r, "path")]


def test_spa_폴백이_실제로_붙는다(app_with_static):
    """폴백이 없으면 아래 테스트들이 전부 무의미하게 통과한다."""
    assert "/{path:path}" in _paths(app_with_static)


def test_헬스체크가_폴백보다_먼저_등록된다(app_with_static):
    paths = _paths(app_with_static)
    fallback = paths.index("/{path:path}")

    for endpoint in ("/healthz", "/readyz"):
        assert endpoint in paths, f"{endpoint} 가 등록되지 않았다"
        assert paths.index(endpoint) < fallback, (
            f"{endpoint} 가 SPA 폴백보다 뒤에 등록됐다 — 폴백이 삼켜서 index.html 이 돌아간다"
        )


def test_api_라우트가_폴백보다_먼저_등록된다(app_with_static):
    paths = _paths(app_with_static)
    fallback = paths.index("/{path:path}")
    api = [p for p in paths if p.startswith("/api/")]

    assert api, f"API 라우트가 하나도 없다. 등록된 경로: {paths}"
    for path in api:
        assert paths.index(path) < fallback, f"{path} 가 SPA 폴백에 가려진다"


def test_폴백이_맨_마지막이다(app_with_static):
    """앞으로 추가되는 라우트도 폴백보다 앞서야 한다."""
    paths = _paths(app_with_static)
    tail = paths[paths.index("/{path:path}") + 1:]
    assert not tail, f"SPA 폴백 뒤에 라우트가 있다 — 가려진다: {tail}"


def test_static이_없으면_폴백을_붙이지_않는다(tmp_path):
    """개발 중에는 Vite 가 담당한다. 이때도 API 는 정상이어야 한다."""
    app = create_app(static_dir=tmp_path / "없음")
    paths = _paths(app)

    assert "/{path:path}" not in paths
    assert "/healthz" in paths
    assert any(p.startswith("/api/") for p in paths), f"등록된 경로: {paths}"
