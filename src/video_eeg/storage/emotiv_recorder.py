"""Native EDF+ recording of Cortex sensor values, without guessed hardware ranges."""
from datetime import datetime
import math

import numpy as np
from video_eeg.storage.session_recorder import SessionRecorder


class EmotivSessionRecorder(SessionRecorder):
    @property
    def _uses_edf(self):
        return True

    def _profile(self):
        names = list(self._acquirer.channel_names)
        if (len(names) != self._n_channels or len(set(names)) != len(names)
                or any(not isinstance(n, str) or not n or len(n) > 16
                       or not n.isascii() or not n.isprintable() for n in names)):
            raise ValueError('Cortex channel names cannot be represented uniquely in EDF.')
        return dict(revision='emotiv-cortex-edfplus-v1', device_type='emotiv_cortex',
                    channel_names=names, unit='uV', reference='unknown', filters='unknown',
                    physical_range_source='per-channel observed sample extrema, not hardware range')

    def _edf_identity_metadata(self):
        return dict(eeg_format='EDF+', native_edf_profile=self._profile(),
                    sfreq=self._sfreq, n_channels=self._n_channels)

    def _write_edf(self, path, data):
        import edfio
        names = self._profile()['channel_names']
        if data.ndim != 2 or data.shape[0] != len(names) or not data.shape[1]:
            raise ValueError('Cortex EEG shape does not match channel names')
        if not float(self._sfreq).is_integer() or self._sfreq <= 0 or not np.isfinite(data).all():
            raise ValueError('EDF+ requires a valid integer rate and finite samples')
        signals = []
        original_count = data.shape[1]
        padding = (-original_count) % int(self._sfreq)
        for name, row in zip(names, data):
            low, high = float(np.min(row)), float(np.max(row))
            pad = max((high-low)*0.001, abs(low)*0.00001, abs(high)*0.00001, 1.0)
            encoded = np.pad(np.asarray(row, dtype=np.float64), (0, padding), mode='edge')
            signals.append(edfio.EdfSignal(encoded, self._sfreq,
                label=name, physical_dimension='uV', physical_range=(low-pad, high+pad),
                prefiltering='unknown'))
        start = datetime.fromisoformat(self._recording_started_at)
        edf = edfio.Edf(signals, recording=edfio.Recording(startdate=start.date()),
            starttime=start.time().replace(tzinfo=None, microsecond=0),
            data_record_duration=1,
            annotations=[edfio.EdfAnnotation(0, None, 'Recording start'),
                         edfio.EdfAnnotation(original_count/self._sfreq, None,
                                             'Acquired data end; remaining samples are padding')])
        with path.open('xb') as handle:
            edf.write(handle)
        saved = edfio.read_edf(path)
        if len(saved.signals) != len(names):
            raise ValueError('EDF+ readback channel count mismatch')
        steps = []
        for name, source, signal in zip(names, data, saved.signals):
            step = (signal.physical_max-signal.physical_min)/65535
            if (signal.label != name or signal.physical_dimension != 'uV'
                    or signal.sampling_frequency != self._sfreq or len(signal.data) != original_count+padding
                    or np.max(np.abs(signal.data[:original_count]-source)) > step*1.01 + 1e-8):
                raise ValueError('EDF+ readback mismatch: '+name)
            steps.append(step)
        return dict(quantization_steps_uv=steps, acquired_samples=original_count,
                    padded_samples=padding, padding_method='repeat final sample; excluded from acquired_samples',
                    physical_ranges_uv=[[s.physical_min, s.physical_max] for s in saved.signals])

    def _edf_export_metadata(self, quantization):
        return dict(eeg_format='EDF+', native_edf_profile=self._profile(),
                    edf_quantization_details=quantization, simulated_eeg=False)
