"""파생물 실패 사유 기록.

사유가 남지 않으면 실패할 때마다 워커 컨테이너 로그를 뒤져야 한다. 로그는
재시작하면 잘리고 시간이 지나면 사라진다 — 실제로 그래서 원인 파악이 늦어졌다.
"""

from types import SimpleNamespace

from poogiegram.worker import DERIVE_ERROR_MAX, _fail


def _asset():
    return SimpleNamespace(derive_status="pending", derive_error=None)


def test_실패하면_상태와_사유가_함께_남는다():
    asset = _asset()
    result = _fail(asset, "이미지를 열 수 없음: OSError: broken data")

    assert asset.derive_status == "failed"
    assert asset.derive_error == "이미지를 열 수 없음: OSError: broken data"
    assert result["error"] == asset.derive_error


def test_긴_사유는_잘라서_저장한다():
    """ffmpeg 출력이 통째로 들어오면 목록 조회가 무거워진다."""
    asset = _asset()
    _fail(asset, "x" * (DERIVE_ERROR_MAX * 3))

    assert len(asset.derive_error) == DERIVE_ERROR_MAX


def test_반환값은_자르지_않는다():
    """로그·작업 결과에는 전체가 남아야 진단할 수 있다."""
    long = "y" * (DERIVE_ERROR_MAX * 2)
    result = _fail(_asset(), long)

    assert result["error"] == long
