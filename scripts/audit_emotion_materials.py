"""Read-only validation of the published combined manifest against local media."""
import argparse
import csv
import hashlib
import json
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from video_eeg.experiment import video_runner as base
from video_eeg.utils.emotion_protocol import prepare, EmotionLibrary
from video_eeg.utils.video_library import VideoAsset

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ffprobe',default=shutil.which('ffprobe'))
    p.add_argument('--files-only',action='store_true',help='Presence only; does not replace full validation')
    args=p.parse_args()
    config=base.load_config(base.CONFIG_DIR/'video_emotion_config.yaml')
    config['_project_dir']=str(base.PROJECT_ROOT)
    library,_=prepare(config,False)
    with (base.PROJECT_ROOT/config['protocol']['session_manifest']).open(encoding='utf-8-sig',newline='') as f:
        rows=list(csv.DictReader(f))
    probe=args.ffprobe
    if not probe:
        candidates=[Path(sys.prefix)/'share/ffpyplayer/ffmpeg/bin/ffprobe.exe']
        probe=next((str(p) for p in candidates if p.is_file()),None)
    if not args.files_only and not probe:
        raise RuntimeError('ffprobe unavailable; supply --ffprobe with its executable path')
    def verify(row):
        path=library.resolve(VideoAsset(row['video_id'],row['video_path']))
        try:
            if not path.is_file():
                raise FileNotFoundError(str(path))
            if not args.files_only:
                if row['sha256']:
                    with path.open('rb') as f:
                        assert hashlib.file_digest(f,'sha256').hexdigest()==row['sha256'],'SHA256 mismatch'
                result=json.loads(subprocess.check_output([probe,'-v','error','-show_format','-show_streams','-of','json',str(path)],timeout=45))
                assert any(s['codec_type']=='video' for s in result['streams']),'No video stream'
                duration=float(result['format']['duration'])
                assert abs(duration-float(row['video_duration_sec']))<.1,'Duration differs from manifest'
                if row['trial_type']=='emotion':
                    assert 5<=duration<=60,'Emotion video outside 5-60 s'
            return None
        except Exception as exc:
            return dict(video_id=row['video_id'],path=str(path),error=str(exc))
    with ThreadPoolExecutor(max_workers=8) as pool:
        failures=[r for r in pool.map(verify,rows) if r]
    report=dict(mode='files-only' if args.files_only else 'ffprobe-and-emotion-sha256',
                total=len(rows),passed=len(rows)-len(failures),failures=failures,
                ordinary_root=str(library.roots['original']),emotion_selected_root=str(library.roots['emotion']))
    folder=base.PROJECT_ROOT/'logs'
    folder.mkdir(exist_ok=True)
    (folder/'emotion_material_audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 1 if failures else 0

if __name__=='__main__':
    raise SystemExit(main())
