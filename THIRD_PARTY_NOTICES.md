# Third-party components

`vendor/eeg-bids-converter` contains the local EEG BIDS converter source with its original MIT LICENSE.
Upstream: https://github.com/Omni-Intel/eeg-bids-converter
It supports optional post-acquisition BIDS export. Its license applies to that component only.

PsychoPy, uv, Python, BrainCo SDK and other runtime dependencies are obtained by the installer;
their respective licenses and hardware requirements apply. This source distribution does not include
real stimulus videos, participant recordings, credentials or a prebuilt Python environment.

The data-quality discussion references [Omni-Intel/oi-eegqc](https://github.com/Omni-Intel/oi-eegqc).

The pending EEGQC handoff exporter uses edfio 0.4.11 (Apache-2.0; https://github.com/the-siesta-group/edfio) to write EDF. Its package and license metadata are included by the Windows runtime builder. EDF quantization does not replace the preserved native float32 recordings.
No oi-eegqc scoring code is embedded or automatically run by this experiment.

Windows 1.0.4 additionally bundles BIDS Validator 3.0.1 (MIT; https://github.com/bids-standard/bids-validator) and Deno 2.9.6 (MIT; https://github.com/denoland/deno) for offline format validation. Package license files are included in the runtime distribution metadata. The validator receives no network permission. The paradigm-specific BrainVision exporter is in src/video_eeg/utils/bids_export.py; it does not depend on MNE at acquisition time.
