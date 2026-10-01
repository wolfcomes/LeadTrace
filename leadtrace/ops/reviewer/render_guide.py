"""Generate portable guides from the same bilingual source used by the UI."""
import argparse
import json
from pathlib import Path
root = Path(__file__).resolve().parents[3]
data = json.loads((root/'leadtrace/frontend/src/review/help/reviewer-guide.json').read_text())
parser=argparse.ArgumentParser(); parser.add_argument('--check',action='store_true'); args=parser.parse_args()
for lang in ('zh','en'):
    title='Reviewer 工作指南' if lang=='zh' else 'Reviewer guide'
    lines=[f'# {title}', '', f"Version: {data['version']}", '', '> Generated from `leadtrace/frontend/src/review/help/reviewer-guide.json`. Edit that source and run `python leadtrace/ops/reviewer/render_guide.py`.', '']
    for section in data['sections']:
        lines += ['## '+section['title_'+lang], '', section[lang], '']
    lines += ['## '+('基团缩写速查' if lang=='zh' else 'Group abbreviation reference'), '', '| Symbol | '+('含义 | 核对要点' if lang=='zh' else 'Meaning | Check')+' |', '|---|---|---|']
    for entry in data['groups']:lines.append(f"| {entry['symbol']} | {entry[lang]} | {entry['note_'+lang]} |")
    lines+=['', 'PDB format reference: https://www.rcsb.org/docs/general-help/identifiers-in-pdb', '']
    path=root/f'docs/reviewer/reviewer-guide.{lang}.md'; text='\n'.join(lines)
    if args.check:
        if not path.exists() or path.read_text()!=text:raise SystemExit(f'Stale generated guide: {path}')
    else:path.write_text(text)
