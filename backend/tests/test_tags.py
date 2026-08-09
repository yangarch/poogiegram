"""드롭 폴더 이름 → 태그 (§5.5).

손으로 하나씩 지정하는 UI만 있으면 아무도 쓰지 않는다. 넣는 시점에 자동으로
붙어야 한다 — 그래서 이 규칙이 태그 기능의 핵심이다.
"""

from pathlib import Path

from poogiegram.ingest.pipeline import TAG_NAME_MAX, prune_empty_dirs, tag_names_from

DROP = Path("/mnt/media/incoming/drop")


def test_폴더_하나면_태그_하나():
    assert tag_names_from(DROP / "푸기 3번째 생일/IMG_1.heic", DROP) == ["푸기 3번째 생일"]


def test_중첩하면_단계마다_태그():
    """마지막 폴더만 쓰면 서로 다른 해의 '생일'이 한 태그로 합쳐진다."""
    assert tag_names_from(DROP / "2025/결혼기념일/IMG_2.heic", DROP) == ["2025", "결혼기념일"]


def test_루트에_그냥_두면_태그가_없다():
    assert tag_names_from(DROP / "IMG_3.heic", DROP) == []


def test_공백을_정규화한다():
    """'푸기  생일'과 '푸기 생일'이 다른 태그로 갈라지면 안 된다."""
    assert tag_names_from(DROP / "  푸기   생일  /a.heic", DROP) == ["푸기 생일"]


def test_숨김_폴더는_태그가_아니다():
    assert tag_names_from(DROP / ".Trash/생일/a.heic", DROP) == ["생일"]


def test_긴_이름은_자른다():
    """폴더 이름은 길어질 수 있는데 헤더 UI 가 감당하지 못한다."""
    names = tag_names_from(DROP / ("가" * 200) / "a.heic", DROP)
    assert len(names[0]) == TAG_NAME_MAX


def test_드롭_폴더_밖이면_태그를_뽑지_않는다():
    """재색인은 originals/ 를 훑는다 — 그 경로는 날짜라서 태그가 되면 안 된다."""
    assert tag_names_from(Path("/mnt/media/originals/2026/08/08/a.heic"), DROP) == []


# ── 빈 폴더 정리 ─────────────────────────────────────────────────────


def test_비워진_폴더를_치운다(tmp_path):
    """두면 SFTP 접속 때 지난 폴더가 쌓여 다음 업로드에 방해가 된다."""
    drop = tmp_path / "drop"
    (drop / "2025/결혼기념일").mkdir(parents=True)

    prune_empty_dirs(drop)

    assert not (drop / "2025").exists()
    assert drop.is_dir(), "드롭 루트까지 지우면 업로드할 곳이 사라진다"


def test_파일이_남은_폴더는_두다(tmp_path):
    drop = tmp_path / "drop"
    keep = drop / "아직 올라오는 중"
    keep.mkdir(parents=True)
    (keep / "a.heic").write_bytes(b"x")
    (drop / "비었음").mkdir()

    prune_empty_dirs(drop)

    assert keep.is_dir()
    assert not (drop / "비었음").exists()


def test_드롭_폴더가_없어도_죽지_않는다(tmp_path):
    prune_empty_dirs(tmp_path / "없음")
