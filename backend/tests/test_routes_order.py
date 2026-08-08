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
    """등록 순서대로 경로를 펼친다.

    include_router 로 넣은 라우트는 app.routes 에 평탄하게 들어가지 않는다.
    _IncludedRouter 객체 하나로 묶여 들어가고 거기엔 .path 가 없다 — 순진하게
    `hasattr(r, "path")` 로 거르면 API 라우트가 통째로 사라져 보인다.

    중첩을 펼쳐도 순서는 그대로다. 묶음이 놓인 자리가 곧 그 라우트들의 매칭
    우선순위이므로, 제자리에 펼치면 실제 매칭 순서와 일치한다.

    Mount(/assets)는 펼치지 않는다 — 자체 경로로 매칭되는 하나의 단위다.
    """
    out: list[str] = []

    def walk(routes) -> None:
        for route in routes:
            path = getattr(route, "path", None)
            if path is not None:
                out.append(path)
                continue
            # 묶음. 버전에 따라 .routes 또는 .router.routes 로 들고 있다.
            nested = getattr(route, "routes", None)
            if nested is None:
                nested = getattr(getattr(route, "router", None), "routes", [])
            walk(nested)

    walk(app.routes)
    return out


def test_paths_헬퍼가_중첩_라우터를_펼친다(app_with_static):
    """헬퍼가 틀리면 아래 순서 검사가 전부 조용히 무의미해진다.

    실제로 include_router 로 넣은 라우트를 못 펼쳐서, 순서 검사가 검사하려던
    대상을 놓친 채 실패했다.
    """
    paths = _paths(app_with_static)
    assert "/api/auth/login" in paths, f"중첩 라우터를 펼치지 못했다: {paths}"


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
