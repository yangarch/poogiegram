"""웹 업로드의 이름 정규화 (§6.6).

태그 이름과 파일명은 **사용자가 정하는 값이 그대로 경로가 된다.** 검증을 빠뜨리면
드롭 폴더 밖에 파일을 쓸 수 있다.
"""

from poogiegram.routes_upload import safe_component


def test_경로_구분자를_막는다():
    """../ 로 드롭 폴더 밖에 쓰는 것을 막는 것이 이 함수의 존재 이유다."""
    assert "/" not in safe_component("../../etc/passwd", "x")
    assert "\\" not in safe_component("..\\..\\windows", "x")


def test_상위_경로가_되지_않는다():
    for attack in ("..", ".", "...", "../"):
        result = safe_component(attack, "안전")
        assert result not in ("", ".", ".."), f"{attack!r} → {result!r}"


def test_한글은_NFC_로_모은다():
    """맥·아이폰이 자모 분리(NFD)로 보내면 같은 이름이 다른 폴더로 갈라진다."""
    nfd = "결혼기념일".encode("utf-8").decode("utf-8")
    decomposed = "결혼"   # '결혼'의 NFD 앞부분
    assert safe_component(decomposed, "x") == "결혼"
    assert safe_component(nfd, "x") == "결혼기념일"


def test_공백을_정규화한다():
    assert safe_component("  푸기   생일  ", "x") == "푸기 생일"


def test_빈_이름은_기본값으로():
    assert safe_component("", "upload") == "upload"
    assert safe_component("   ", "upload") == "upload"


def test_경로_문자만_있으면_안전한_이름이_남는다():
    """치환 결과가 '___' 같은 모양이어도 된다 — 경로로 해석되지만 않으면 안전하다."""
    result = safe_component("///", "upload")
    assert result and "/" not in result


def test_제어문자를_지운다():
    assert "\x00" not in safe_component("a\x00b", "x")
    assert "\n" not in safe_component("a\nb", "x")


def test_확장자는_남는다():
    """인제스트가 MIME 검사를 하지만 확장자도 진단에 쓰인다."""
    assert safe_component("IMG_1234.HEIC", "x") == "IMG_1234.HEIC"


# ── 계정 아이디 (§8) ─────────────────────────────────────────────────


def test_아이디는_소문자로_통일된다():
    """대소문자를 구분하면 Kiseok 으로 만들고 kiseok 으로 로그인하려다 막힌다."""
    from poogiegram.cli import _normalize_username

    assert _normalize_username("Kiseok") == "kiseok"
    assert _normalize_username("  KISEOK  ") == "kiseok"


def test_쓸_수_없는_아이디는_거부한다():
    import pytest

    from poogiegram.cli import _normalize_username

    for bad in ("a", "-nope", "한글", "with space", "x" * 40, ""):
        with pytest.raises(SystemExit):
            _normalize_username(bad)


def test_쓸_수_있는_아이디():
    from poogiegram.cli import _normalize_username

    for good in ("kiseok", "my.wife", "poogie-2", "user_1", "ab"):
        assert _normalize_username(good) == good
