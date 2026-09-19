"""Content-pinned EOF exceptions; never a general missing-frame tolerance."""
from pathlib import Path
import hashlib
import json
import math

AUDITED_NAME = "neutral_neutral_0833_00000235.mp4"
AUDITED_SHA256 = "a62d3f51ff682332ad28a0b1844cc7a1393dba3bca8a4f9069eb4474238bbb31"
AUDITED_EOF_NOTE = "sha256_verified_terminal_frame_count_hold_nominal_end_v1"
_AUDIT = json.loads(Path(__file__).with_name("verified_video_eof.json").read_text(encoding="utf-8"))
PROFILES = _AUDIT["profiles"]
BLOCKED = _AUDIT.get("blocked", {})


def verified_terminal_frame_count(filename, declared_frames, fps):
    """Accept only the audited bytes, timing metadata and audited one/two-frame discrepancy."""
    path = Path(filename)
    profile = PROFILES.get(path.name)
    if profile is None or declared_frames != profile["declared_frames"]:
        return None
    decoded = profile["decoded_frames"]
    if declared_frames - decoded not in (1, 2) or decoded != profile["ffmpeg_frames"]:
        return None
    if not math.isfinite(fps) or abs(fps - profile["fps"]) > 0.000001:
        return None
    try:
        with path.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
    except OSError:
        return None
    return decoded if digest == profile["sha256"] else None


def check_known_bad_materials(filenames):
    """Reject exact known-corrupt bytes before a formal Session starts; read only."""
    bad = []
    for filename in filenames:
        path = Path(filename)
        profile = BLOCKED.get(path.name)
        if profile is None:
            continue
        with path.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        if digest == profile["sha256"]:
            bad.append(path.name)
    if bad:
        raise RuntimeError(
            "材料已知不完整：" + "、".join(bad) + "\n"
            "本 Session 暂不能开始，尚未启动正式采集。\n"
            "请保留原数据，提供完整原片由维护人员核验。\n"
            "不要删除进度、跳过该片或用转码后的短片替代。\n"
            "详见 README 的‘视频解码错误’处理说明。"
        )
