"""Copy native subject records without changing their recovery contract (stdlib only)."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys
from uuid import uuid4


ROOTS = {
    'sourcedata/v1': 'v1', 'sourcedata/legacy17': 'v1',
    'video_question_complete_runs': 'v1',
    'sourcedata/v2': 'v2', 'sourcedata/emotion-v2': 'v2',
    'video_emotion_eeg_runs/protocol_emotion_v2': 'v2',
}
for device in ('', '_neuracle', '_brainco'):
    for scope in ('', '_emotion_only'):
        name = 'v3' + device + scope
        ROOTS['sourcedata/' + name] = name


def safe(path):
    """Reject symlinks AND Windows junction/reparse points, including ancestors."""
    path = Path(os.path.abspath(path))
    for item in (path, *path.parents):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError(f'拒绝链接或 junction：{item}')
    return path


def files(folder):
    folder = safe(folder)
    if not folder.exists():
        return []
    result = []
    def walk_error(error):
        raise error
    for base, dirs, names in os.walk(folder, followlinks=False, onerror=walk_error):
        for name in dirs + names:
            safe(Path(base) / name)
        for name in names:
            path = Path(base) / name
            if not path.is_file():
                raise ValueError(f'不是普通文件：{path}')
            result.append(path)
    return sorted(result)


def digest(path):
    safe(path)
    before = path.stat()
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            h.update(block)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError(f'文件正在变化，请退出采集后重试：{path}')
    return {'bytes': after.st_size, 'sha256': h.hexdigest()}


def inventory(folder):
    return {p.relative_to(folder).as_posix(): digest(p) for p in files(folder)}


def discover(data):
    subjects, states = {}, set()
    all_files = files(data)
    for relative, protocol in ROOTS.items():
        root = data / relative
        if not root.exists():
            continue
        for subject in sorted(root.iterdir()):
            if not subject.is_dir():
                continue
            contents = [p for p in all_files if p.is_relative_to(subject)]
            if not contents:
                continue
            found = [p for p in contents if p.name == 'session_state.json']
            if not found:
                raise ValueError(f'目录有文件但缺少 session_state.json，需人工核对：{subject}')
            for p in found:
                # Ensure the standard launcher can actually find the copied state.
                parts = p.relative_to(subject).parts
                valid = (len(parts) == 2 and parts[0].startswith('session_')) or (
                    len(parts) == 3 and parts[0].startswith('run_') and parts[1].startswith('session_'))
                if not valid:
                    raise ValueError(f'无法自动识别的 Session 层级：{p}')
                if not isinstance(json.loads(p.read_text(encoding='utf-8-sig')), dict):
                    raise ValueError(f'状态不是 JSON 对象：{p}')
                states.add(p)
            key = (protocol, subject.name.casefold())
            if key in subjects:
                raise ValueError(f'同协议同编号存在多个根目录：{subjects[key]} 和 {subject}')
            subjects[key] = subject
    unknown = [p for p in all_files if p.name == 'session_state.json' and p not in states
               and not p.is_relative_to(data / 'sourcedata/demo')
               and not p.is_relative_to(data / '_record_migrations')]
    if unknown:
        raise ValueError('发现未支持的进度位置（不猜测协议）：\n' + '\n'.join(map(str, unknown)))
    return subjects


def plan(source, target):
    source, target = safe(source), safe(target)
    if source == target or source.is_relative_to(target) or target.is_relative_to(source):
        raise ValueError('源、目标数据目录不能相同或互相包含。')
    if not source.is_dir():
        raise ValueError(f'源数据目录不存在：{source}')
    old, new = discover(source), discover(target)
    if not old:
        raise ValueError('未发现支持的正式被试记录；请核对实际数据目录。')
    result = []
    for key, subject in old.items():
        relative = subject.relative_to(source)
        destination = target / relative
        if key in new or destination.exists():
            raise ValueError(f'目标已有该被试，禁止覆盖或合并：{new.get(key, destination)}')
        print(f'检查 {relative}', flush=True)
        manifest = inventory(subject)
        result.append(dict(protocol=key[0], subject=subject.name,
                           relative=relative.as_posix(), files=manifest))
    return result


def migrate(source, target, apply=False):
    source, target = safe(source), safe(target)
    entries = plan(source, target)
    total = sum(v['bytes'] for e in entries for v in e['files'].values())
    print(f'{len(entries)} 个被试目录，{total:,} 字节；保留原目录层级，不转换协议。')
    if not apply:
        print('预览通过，未写入文件。确认已退出两个程序后，加 --apply 执行。')
        return entries
    target.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(target).free < total + 64 * 1024 * 1024:
        raise ValueError('目标磁盘剩余空间不足（另预留64 MiB）。')
    audit = safe(target / '_record_migrations')
    audit.mkdir(exist_ok=True)
    # An interrupted run must be reviewed, not automatically merged or deleted.
    lock = audit / 'migration.lock'
    with lock.open('x', encoding='utf-8') as stream:
        stream.write(f'pid={os.getpid()}\n')
    run = audit / uuid4().hex
    run.mkdir()
    receipt = dict(source=str(source), target=str(target), status='copying',
                   entries=entries, committed=[])
    def save_receipt():
        temp = run / 'receipt.tmp'
        temp.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(run / 'receipt.json')
    try:
        save_receipt()
        for e in entries:
            src, staged = source / e['relative'], run / 'staged' / e['relative']
            for relative in e['files']:
                dest = safe(staged / relative)
                dest.parent.mkdir(parents=True, exist_ok=True)
                with safe(src / relative).open('rb') as inp, dest.open('xb') as out:
                    shutil.copyfileobj(inp, out, length=4 * 1024 * 1024)
                shutil.copystat(src / relative, dest)
            if inventory(staged) != e['files']:
                raise ValueError(f'副本 SHA256 校验失败：{staged}')
        # Repeat the entire preflight before exposing any copied records.
        if plan(source, target) != entries:
            raise ValueError('复制期间源记录发生变化，停止提交。')
        for e in entries:
            dest = safe(target / e['relative'])
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                raise ValueError(f'目标在复制期间出现同名目录：{dest}')
            # On Windows rename refuses an existing destination, including empty directories.
            (run / 'staged' / e['relative']).rename(dest)
            receipt['committed'].append(e['relative'])
            save_receipt()
            if inventory(dest) != e['files']:
                raise ValueError(f'提交后校验失败：{dest}')
        receipt['status'] = 'verified'
        save_receipt()
        lock.unlink()
        print(f'复制与 SHA256 校验完成，旧记录未修改。回执：{run / "receipt.json"}')
        print('请用原协议、设备、视频范围、编号和Session核对进度；兼容性仍由实验程序校验。')
    except BaseException as exc:
        receipt['status'] = 'failed'
        receipt['error'] = str(exc)
        save_receipt()
        print(f'迁移中断，保留暂存、副本和锁供核对，不自动回滚或删除：{run}', file=sys.stderr)
        raise
    return entries


def main():
    parser = argparse.ArgumentParser(description='自动识别标准记录目录，完整复制并校验；默认只预览。')
    parser.add_argument('--old', required=True, type=Path, help='旧项目根目录')
    parser.add_argument('--new', type=Path, default=Path(__file__).resolve().parents[2], help='新项目根目录（默认脚本所在项目）')
    parser.add_argument('--source-data', type=Path, help='自定义旧 data 目录（包含 sourcedata，而非 sourcedata 本身）')
    parser.add_argument('--target-data', type=Path, help='自定义新 data 目录，须已与新版运行配置对应')
    parser.add_argument('--apply', action='store_true', help='确认两个实验程序均已关闭，执行复制')
    args = parser.parse_args()
    try:
        for project in (args.old, args.new):
            safe(project)
            if not any((project / p).is_file() for p in ('main.py', 'run_experiment.bat', 'video_eeg/__init__.py')):
                raise ValueError(f'不是可识别的源码项目根目录：{project}')
        migrate(args.source_data or args.old / 'data', args.target_data or args.new / 'data', args.apply)
    except (OSError, ValueError) as exc:
        print(f'停止：{exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
