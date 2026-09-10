"""Create ten synthetic practice clips; no research stimuli or recordings needed."""
from pathlib import Path
import json
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def main():
    folder = ROOT / 'stimuli' / 'demo'
    folder.mkdir(parents=True, exist_ok=True)
    questions = []
    for index in range(10):
        path = folder / f'demo_{index + 1:02d}.mp4'
        shape = index % 2
        if not path.is_file():
            temp = path.with_name(path.stem + '.tmp.mp4')
            writer = cv2.VideoWriter(str(temp), cv2.VideoWriter_fourcc(*'mp4v'), 24, (640, 360))
            if not writer.isOpened():
                raise RuntimeError(f'Cannot create practice video: {temp}')
            try:
                for frame in range(120):
                    canvas = np.zeros((360, 640, 3), dtype=np.uint8)
                    x = 70 + frame * 4
                    if shape == 0:
                        cv2.circle(canvas, (x, 180), 45, (70, 190, 250), -1)
                    else:
                        cv2.rectangle(canvas, (x - 45, 135), (x + 45, 225), (250, 190, 70), -1)
                    cv2.putText(canvas, 'PRACTICE', (20, 35), cv2.FONT_HERSHEY_SIMPLEX, .7, (220, 220, 220), 1)
                    writer.write(canvas)
            finally:
                writer.release()
            temp.replace(path)
        cap = cv2.VideoCapture(str(path))
        ok, _ = cap.read()
        cap.release()
        if not ok:
            raise RuntimeError(f'Practice video cannot be decoded: {path}')
        questions.append(dict(video_id=path.stem, video_file=path.name, duration_sec=5,
            status='ready', review_status='authored_practice', source='synthetic_practice',
            question='视频中移动的图形是什么？', options=dict(A='圆形', B='正方形', C='三角形', D='五角星'),
            answer='A' if shape == 0 else 'B'))
    (folder / 'question_bank.json').write_text(json.dumps(dict(questions=questions), ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Practice materials ready: {folder}')


if __name__ == '__main__':
    main()
