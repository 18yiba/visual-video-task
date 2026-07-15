from tasks.image_core import session_type_for_id


def test_labeling_sessions_stay_labeling() -> None:
    assert session_type_for_id(1) == "labeling"
    assert session_type_for_id(2) == "labeling"


def test_extended_denoise_sessions_are_supported() -> None:
    for session_id in range(3, 11):
        assert session_type_for_id(session_id) == "denoise"
