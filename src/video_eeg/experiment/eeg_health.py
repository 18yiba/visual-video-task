"""Detect missing EEG samples; this does not diagnose battery or impedance."""
import math


class EegAcquisitionError(RuntimeError):
    """A latched acquisition fault which must stop the current attempt."""


class SampleWatchdog:
    def __init__(self, now, *, timeout=5.0, startup_timeout=10.0):
        if not all(math.isfinite(v) and v > 0 for v in (timeout, startup_timeout)):
            raise ValueError('EEG watchdog timeouts must be finite and positive')
        self.timeout=timeout;self.startup_timeout=startup_timeout
        self.started=now;self.last_sample_time=now;self.last_count=0

    def observe(self, count, now):
        if count > self.last_count:
            self.last_sample_time=now;self.last_count=count
        age=max(0.,now-self.last_sample_time)
        limit=self.timeout if count else self.startup_timeout
        return dict(sample_count=count,seconds_without_new_samples=age,
                    timeout_sec=limit,status='no_samples_timeout' if age>=limit else 'ok',
                    last_sample_observed_monotonic_sec=self.last_sample_time if count else None)


def failure_message(exc):
    return ('EEG采集异常，实验已停止\n\n'
            f'检测结果：{str(exc)[:450]}\n\n'
            '请保持坐姿并联系主试；不要继续作答。\n'
            '这不等于确认放大器没电或关机。请主试检查设备开机状态、连接及采集软件。\n'
            '数据已进入保存流程；未完成的视频下次重播。\n\n'
            '请主试按空格结束本次运行，恢复连接后重新启动。')
