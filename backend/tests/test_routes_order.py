"""라우트 등록 순서 (§3).

SPA 폴백 `/{path:path}` 는 **모든 경로에 매칭된다.** FastAPI 는 등록 순서대로
매칭하므로, 이 라우트가 먼저 등록되면 뒤에 정의된 라우트가 전부 삼켜진다.

실제로 이 일이 있었다: 프런트엔드를 붙인 뒤 `/healthz` 가 index.html 을 200 으로
돌려주었고, 헬스체크가 JSON 파싱에 실패해 컨테이너가 unhealthy 로 떨어졌다.
앱 로그에는 `GET /healthz 200 OK` 만 찍혀서 원인이 한눈에 보이지 않았다.

static/ 이 없으면 폴백이 등록되지 않아 버그가 재현되지 않는다. 그래서 이 테스트는
static/ 을 **있는 상태로 만들고** 검사한다.
"""

import importlib

import pytest


@pytest.fixture
def app_with_static(tmp_path, monkeypatch):
    """빌드 산출물이 있는 상태를 만든다.

    소스 트리에 만들지 않는다 — 컨테이너에서 마운트해 돌릴 때 쓰기 권한이 없고,
    테스트가 중간에 죽으면 static/ 이 남는다. STATIC_DIR 로 임시 경로를 가리킨다.
    """
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<!doctype html><title>poogiegram</title>")
    monkeypatch.setenv("STATIC_DIR", str(static))

    # 라우트는 임포트 시점에 등록되므로 다시 읽어야 한다
    main = importlib.reload(importlib.import_module("poogiegram.main"))
    assert main._STATIC.is_dir(), "픽스처가 static/ 을 만들지 못했다"
    yield main.app

    # 다음 테스트가 STATIC_DIR 없는 모듈을 보도록 되돌린다
    monkeypatch.undo()
    importlib.reload(main)


def _paths(app) -> list[str]:
    return [r.path for r in app.routes if hasattr(r, "path")]


def test_health_routes_registered_before_spa_fallback(app_with_static):
    paths = _paths(app_with_static)
    fallback = paths.index("/{path:path}")

    for endpoint in ("/healthz", "/readyz"):
        assert endpoint in paths, f"{endpoint} 가 등록되지 않았다"
        assert paths.index(endpoint) < fallback, (
            f"{endpoint} 가 SPA 폴백보다 뒤에 등록됐다 — 폴백이 삼켜서 index.html 이 돌아간다"
        )


def test_spa_fallback_is_last(app_with_static):
    """앞으로 추가되는 라우트도 폴백보다 앞서야 한다."""
    paths = _paths(app_with_static)
    assert paths[-1] == "/{path:path}", (
        f"SPA 폴백이 마지막이 아니다. 뒤에 있는 라우트: {paths[paths.index('/{path:path}') + 1:]}"
    )


def test_api_routes_registered_before_spa_fallback(app_with_static):
    paths = _paths(app_with_static)
    fallback = paths.index("/{path:path}")
    api = [p for p in paths if p.startswith("/api/")]

    assert api, "API 라우트가 하나도 없다 — 라우터 등록이 빠졌는지 확인"
    for path in api:
        assert paths.index(path) < fallback, f"{path} 가 SPA 폴백에 가려진다"
