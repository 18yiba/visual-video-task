"""One continuous, optional Neuracle movement recording per acquisition run."""
from video_eeg.experiment.facial_recording import FacialRecorder, FacialRecordingError


class ActionRecorder(FacialRecorder):
    device = 'Action_CAMERA'
    filename_suffix = 'action'
    log_filename = 'action_recording_log.jsonl'
    relative_time_column = 'relative_experiment_onset_sec'

    def __init__(self, directory):
        super().__init__(directory, 'experiment', 1)

    def _log(self, status, **fields):
        super()._log(status, recording_scope='continuous_acquisition_run',
                    experiment_completed=getattr(self, 'experiment_completed', False), **fields)

    def _validate_coverage(self, onset, offset, duration, decoded):
        super()._validate_coverage(onset, offset, duration, decoded)
        if decoded <= max(duration, offset-onset):
            raise FacialRecordingError('全程动作录像时长必须长于实验记录区间。')
