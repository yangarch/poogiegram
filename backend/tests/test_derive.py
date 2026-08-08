"""파생물 생성 검증 (§6.2).

HEIC 는 파생물이 없으면 크롬에서 아무것도 안 보인다 — 여기가 틀리면
사진이 들어와도 화면이 빈다.
"""

import pytest
from PIL import Image

from poogiegram.ingest.derive import DISPLAY, PREVIEW, THUMB, DeriveError, derived_dir, generate

SHA = "abc123" + "0" * 58


def _jpeg(path, size=(4000, 3000), orientation=None):
    img = Image.new("RGB", size, (120, 60, 30))
    if orientation is not None:
        exif = img.getexif()
        exif[0x0112] = orientation      # EXIF Orientation
        img.save(path, exif=exif)
    else:
        img.save(path)
    return path


def test_썸네일과_프리뷰가_생긴다(tmp_path):
    src = _jpeg(tmp_path / "a.jpg")
    out = tmp_path / "derived"
    result = generate(src, SHA, "image", out)

    d = derived_dir(out, SHA)
    assert (d / "thumb_320.webp").exists()
    assert (d / "preview_1600.webp").exists()
    assert max(Image.open(d / "thumb_320.webp").size) == THUMB
    assert max(Image.open(d / "preview_1600.webp").size) == PREVIEW
    assert result.display is None


def test_display는_필요할_때만_생긴다(tmp_path):
    """HEIC 처럼 브라우저가 못 여는 형식에만 만든다. 나머지는 원본을 그대로 쓴다."""
    src = _jpeg(tmp_path / "a.jpg")
    out = tmp_path / "derived"
    generate(src, SHA, "image", out, needs_display=True)
    display = derived_dir(out, SHA) / "display.jpg"
    assert display.exists()
    assert max(Image.open(display).size) == DISPLAY


def test_원본보다_크게_늘리지_않는다(tmp_path):
    """작은 사진을 확대하면 용량만 늘고 화질은 나아지지 않는다."""
    src = _jpeg(tmp_path / "small.jpg", size=(200, 150))
    out = tmp_path / "derived"
    generate(src, SHA, "image", out)
    assert Image.open(derived_dir(out, SHA) / "preview_1600.webp").size == (200, 150)


def test_EXIF_회전이_픽셀에_반영된다(tmp_path):
    """이걸 빼면 아이폰 세로 사진이 전부 누워서 나온다."""
    src = _jpeg(tmp_path / "portrait.jpg", size=(400, 200), orientation=6)  # 90° CW
    out = tmp_path / "derived"
    generate(src, SHA, "image", out)
    w, h = Image.open(derived_dir(out, SHA) / "preview_1600.webp").size
    assert h > w, "가로 사진이 세로로 회전돼야 한다"


def test_사용자_회전이_적용된다(tmp_path):
    """원본은 그대로 두고 파생물에만 적용한다 (§5.3)."""
    src = _jpeg(tmp_path / "a.jpg", size=(400, 200))
    out = tmp_path / "derived"
    generate(src, SHA, "image", out, rotation=90)
    w, h = Image.open(derived_dir(out, SHA) / "preview_1600.webp").size
    assert h > w

    assert Image.open(src).size == (400, 200), "원본은 변경되지 않는다"


def test_임시파일이_남지_않는다(tmp_path):
    """중단 시 '있는데 깨진' 파일이 남으면 다음 실행에서 정상으로 오인된다."""
    src = _jpeg(tmp_path / "a.jpg")
    out = tmp_path / "derived"
    generate(src, SHA, "image", out)
    assert list(derived_dir(out, SHA).glob("*.tmp")) == []


def test_해시로_디렉터리를_쪼갠다(tmp_path):
    """3만 장이 한 디렉터리에 들어가면 ls 하나에도 몇 초가 걸린다."""
    d = derived_dir(tmp_path, SHA)
    assert d.relative_to(tmp_path).parts == ("ab", "c1", SHA)


def test_깨진_파일은_DeriveError(tmp_path):
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"not an image")
    with pytest.raises(DeriveError):
        generate(bad, SHA, "image", tmp_path / "derived")


def test_재실행하면_덮어쓴다(tmp_path):
    """재시도나 회전 변경 시 파생물을 다시 만들 수 있어야 한다."""
    src = _jpeg(tmp_path / "a.jpg", size=(400, 200))
    out = tmp_path / "derived"
    generate(src, SHA, "image", out)
    generate(src, SHA, "image", out, rotation=90)
    w, h = Image.open(derived_dir(out, SHA) / "preview_1600.webp").size
    assert h > w, "두 번째 결과가 반영돼야 한다"


def test_파생물이_그룹에서_읽을_수_있다(tmp_path):
    """tempfile 은 0600 으로 만들고 rename 은 그 모드를 가져간다.

    그대로 두면 nginx(www-data)가 읽지 못해 화면은 뜨는데 사진만 안 보인다.
    실제로 그렇게 배포됐다가 setup-nginx.sh 의 점검에서 잡혔다.
    """
    import stat

    src = _jpeg(tmp_path / "a.jpg")
    out = tmp_path / "derived"
    generate(src, SHA, "image", out, needs_display=True)

    d = derived_dir(out, SHA)
    for f in ("thumb_320.webp", "preview_1600.webp", "display.jpg"):
        mode = stat.S_IMODE((d / f).stat().st_mode)
        assert mode & stat.S_IRGRP, f"{f} 를 그룹이 읽을 수 없다 (mode {oct(mode)})"

    assert stat.S_IMODE(d.stat().st_mode) & stat.S_IXGRP, "디렉터리에 그룹 진입 권한이 없다"


def test_디렉터리에_setgid가_남는다(tmp_path):
    """setgid 가 없으면 파일이 poogiegram 그룹을 물려받지 못한다.

    컨테이너 프로세스의 주 그룹은 app 이고 poogiegram 은 보조 그룹이다.
    setgid 디렉터리 안에서 만든 파일만 부모의 그룹을 따라간다 — 이 비트가 빠지면
    파일이 0640 이어도 그룹이 app 이라 nginx 가 읽지 못한다.

    chmod 는 넘긴 모드를 그대로 쓰므로, 모드에서 2000 을 빠뜨리면 상위에서
    물려받은 setgid 까지 **지워버린다.** 실수하기 쉬운 지점이라 고정해둔다.
    """
    import stat

    src = _jpeg(tmp_path / "a.jpg")
    out = tmp_path / "derived"
    generate(src, SHA, "image", out)

    d = derived_dir(out, SHA)
    # 해시 단계 디렉터리까지 전부 확인한다 — 중간에서 끊기면 그 아래가 함께 무너진다
    for path in (out / SHA[:2], out / SHA[:2] / SHA[2:4], d):
        assert stat.S_IMODE(path.stat().st_mode) & stat.S_ISGID, (
            f"{path.name} 에 setgid 가 없다 — 파일이 app 그룹으로 생겨 nginx 가 못 읽는다"
        )


def test_setgid없이_있던_디렉터리도_복구된다(tmp_path):
    """권한 수정 이전 배포에서 만들어진 디렉터리가 그대로 남아 있을 수 있다."""
    import stat

    out = tmp_path / "derived"
    stale = derived_dir(out, SHA)
    stale.mkdir(parents=True)
    stale.chmod(0o700)

    generate(_jpeg(tmp_path / "a.jpg"), SHA, "image", out)

    assert stat.S_IMODE(stale.stat().st_mode) & stat.S_ISGID
    assert stat.S_IMODE(stale.stat().st_mode) & stat.S_IXGRP
