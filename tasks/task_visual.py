"""Visual video-EEG task: marker proxy and phase callbacks."""

from __future__ import annotations

from typing import Any, Callable

PHASE_LABELS = {
    "session_start": ("实验开始", "请保持放松，准备观看视频"),
    "baseline_start": ("基线采集", "睁眼注视中央十字，保持静止"),
    "baseline_end": ("基线结束", "即将开始视频 trial"),
    "trial_start": ("Trial 开始", "请注视屏幕中央"),
    "fixation_on": ("注视点", "请注视 + ，保持头部静止"),
    "fixation_off": ("注视结束", "视频即将播放"),
    "video_on": ("视频播放", "请专注观看，尽量减少眨眼"),
    "video_off": ("视频结束", "请保持静止"),
    "blank_on": ("空屏", "短暂空屏，请保持静止"),
    "blank_off": ("空屏结束", "即将进入评分"),
    "rating_on": ("行为评分", "请根据真实感受打分"),
    "rating_off": ("评分完成", "感谢反馈"),
    "iti_on": ("休息", "短暂休息，准备下一个视频"),
    "iti_off": ("休息结束", "准备下一个 trial"),
    "trial_end": ("Trial 结束", ""),
    "session_end": ("实验结束", "感谢参与"),
}


class _ConsoleProxy:
    def __init__(self, console: Any, task: "Task") -> None:
        self._console = console
        self._task = task

    def print(self, *args: Any, **kwargs: Any) -> None:
        self._console.print(*args, **kwargs)
        self._task.on_console_print(args)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._console, name)


class _MarkerBackendProxy:
    def __init__(self, backend: Any, task: "Task") -> None:
        self._backend = backend
        self._task = task

    def send(self, label: int, timestamp=None) -> None:
        self._backend.send(label, timestamp=timestamp)
        self._task.on_marker_label(label)

    def send_event(self, event_name: str, timestamp=None) -> None:
        if hasattr(self._backend, "send_event"):
            self._backend.send_event(event_name, timestamp=timestamp)
        self._task.on_protocol_event(event_name)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._backend, name)


class Task:
    """Bridge marker events to optional UI callbacks (Streamlit or external display)."""

    def __init__(self) -> None:
        self._console: Any | None = None
        self._phase_callback: Callable[[str, dict[str, Any]], None] | None = None
        self._current_phase = "ready"
        self._current_payload: dict[str, Any] = {}

    def set_phase_callback(self, callback: Callable[[str, dict[str, Any]], None] | None) -> None:
        self._phase_callback = callback

    @property
    def current_phase(self) -> str:
        return self._current_phase

    @property
    def current_payload(self) -> dict[str, Any]:
        return dict(self._current_payload)

    def wrap_console(self, console: Any) -> Any:
        self._console = console
        return _ConsoleProxy(console, self)

    def wrap_marker_backend(self, backend: Any) -> Any:
        return _MarkerBackendProxy(backend, self)

    def on_protocol_event(self, event_name: str, **payload: Any) -> None:
        self._current_phase = event_name
        self._current_payload = dict(payload)
        if self._phase_callback is not None:
            self._phase_callback(event_name, self._current_payload)
        if self._console is not None:
            title, subtitle = PHASE_LABELS.get(event_name, (event_name, ""))
            detail = " ".join(f"{key}={value}" for key, value in payload.items())
            message = f"[{title}] {subtitle}"
            if detail:
                message = f"{message} ({detail})"
            self._console.print(message)

    def on_marker_label(self, label: int) -> None:
        if self._console is not None:
            self._console.print(f"[trigger] code={label}")

    def on_console_print(self, args: tuple[Any, ...]) -> None:
        del args

    def phase_display(self, event_name: str) -> tuple[str, str]:
        return PHASE_LABELS.get(event_name, (event_name, ""))

    def close(self) -> None:
        self._current_phase = "closed"
