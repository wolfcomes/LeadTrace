"""Render the bilingual reviewer source as portable Markdown and offline HTML."""
import argparse
from html import escape
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / 'leadtrace/frontend/src/review/help/reviewer-guide.json'
PUBLIC = ROOT / 'leadtrace/frontend/public/reviewer-guide'
DOCS = ROOT / 'docs/reviewer'


def e(value):
    return escape(str(value), quote=True)


def render_block(block, lang):
    value, kind = block[lang], block['type']
    if kind == 'paragraph':
        return f'<p>{e(value)}</p>', [value, '']
    if kind == 'note':
        return f'<aside class="note"><strong>{"提醒" if lang == "zh" else "Remember"}</strong><p>{e(value)}</p></aside>', ['> ' + value, '']
    if kind == 'steps':
        return '<ol>' + ''.join(f'<li>{e(x)}</li>' for x in value) + '</ol>', [f'{i}. {x}' for i, x in enumerate(value, 1)] + ['']
    if kind == 'table':
        head, *rows = value
        html = '<div class="table-scroll" tabindex="0"><table><thead><tr>' + ''.join(f'<th scope="col">{e(x)}</th>' for x in head) + '</tr></thead><tbody>'
        html += ''.join('<tr>' + ''.join(f'<td>{e(x)}</td>' for x in row) + '</tr>' for row in rows) + '</tbody></table></div>'
        md = ['| ' + ' | '.join(str(x).replace('|', '\\|') for x in row) + ' |' for row in value]
        md.insert(1, '|' + '|'.join('---' for _ in head) + '|')
        return html, md + ['']
    if kind in ('example', 'flow'):
        text = '\n'.join(value) if isinstance(value, list) else value
        return f'<pre class="example">{e(text)}</pre>', ['```text', text, '```', '']
    if kind == 'question':
        return f'<details class="exercise"><summary>{e(value["question"])}</summary><p>{e(value["answer"])}</p></details>', [f'**{value["question"]}**', '', value['answer'], '']
    if kind == 'figure':
        asset = f'images/{block["asset"]}.{lang}.png'
        caption = ('点击图片可打开原图。' if lang == 'zh' else 'Open the image for full size.')
        return f'<figure><a href="{asset}" target="_blank" rel="noopener"><img src="{asset}" alt="{e(value)}" loading="lazy" decoding="async"></a><figcaption>{e(value)} <span>{caption}</span></figcaption></figure>', [f'![{value}](../../leadtrace/frontend/public/reviewer-guide/{asset})', '', value, '']
    raise ValueError(f'Unknown guide block: {kind}')


def render(data, lang):
    zh = lang == 'zh'
    title = 'Reviewer 图文上手手册' if zh else 'Reviewer illustrated handbook'
    subtitle = '从第一篇论文开始，逐项学会核对与交接。' if zh else 'Learn to check and hand off a paper, one record at a time.'
    nav, body = [], []
    md = [f'# {title}', '', f'Version: {data["version"]}', '', '> Generated from `leadtrace/frontend/src/review/help/reviewer-guide.json`. Edit that source and run `python leadtrace/ops/reviewer/render_guide.py`.', '']
    for s in data['sections']:
        sid, heading = s['id'], s['title_' + lang]
        nav.append(f'<a href="#{e(sid)}">{e(heading)}</a>')
        content = [f'<section id="{e(sid)}"><h2>{e(heading)}</h2><p class="lead">{e(s[lang])}</p>']
        md += ['## ' + heading, '', s[lang], '']
        for block in s.get('blocks', []):
            html, markdown = render_block(block, lang)
            content.append(html)
            md += markdown
        content.append('<a class="back-top" href="#top">' + ('返回目录 ↑' if zh else 'Back to contents ↑') + '</a></section>')
        body.append(''.join(content))
    group_title = '19 · 基团缩写速查' if zh else '19 · Substituent abbreviation reference'
    nav.append(f'<a href="#groups">{group_title}</a>')
    intro = '缩写只有结合原文定义和连接点才有意义。先查作者的图例，再查此表；大小写、前缀和连接原子不能省略。可使用浏览器查找（Ctrl+F / ⌘F）。' if zh else 'Read source definitions and attachment points first. Case, prefixes and attachment atoms matter. Use your browser’s Find command (Ctrl+F / ⌘F).'
    rows = [['Symbol', '含义' if zh else 'Meaning', '核对要点' if zh else 'Check']] + [[x['symbol'], x[lang], x['note_' + lang]] for x in data['groups']]
    table, table_md = render_block({'type': 'table', lang: rows}, lang)
    body.append(f'<section id="groups"><h2>{group_title}</h2><p>{intro}</p>{table}</section>')
    md += ['## ' + group_title, '', intro, ''] + table_md
    refs = ('参考：PDB 标识符格式' if zh else 'Reference: PDB identifier formats')
    ref_url = 'https://www.rcsb.org/docs/general-help/identifiers-in-pdb'
    md += [f'[{refs}]({ref_url})', '']
    other, other_label = ('en', 'English') if zh else ('zh', '中文')
    html = f'''<!doctype html>
<html lang="{'zh-CN' if zh else 'en'}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="description" content="{e(subtitle)}"><title>{e(title)} · LeadTrace</title><link rel="stylesheet" href="fonts.css"><link rel="stylesheet" href="guide.css"></head>
<body><a class="skip" href="#content">{'跳到正文' if zh else 'Skip to content'}</a>
<header id="top"><div class="eyebrow">LEADTRACE / REVIEWER HANDBOOK</div><h1>{e(title)}</h1><p>{e(subtitle)}</p><div class="meta">v{e(data['version'])} <span>·</span> {'适合初次参与文献审核的人员' if zh else 'For first-time literature reviewers'}</div><nav class="tools" aria-label="{'手册选项' if zh else 'Handbook options'}"><a href="{other}.html" lang="{other}">{other_label}</a><a href="#start">{'开始学习' if zh else 'Start here'}</a><a href="#groups">{'查缩写' if zh else 'Find abbreviations'}</a></nav><p class="print-help">{'离线可读 · 点击截图放大 · 浏览器 Ctrl+P / ⌘P 可打印或另存为 PDF' if zh else 'Works offline · Open screenshots full size · Ctrl+P / ⌘P to print or save as PDF'}</p></header>
<div class="layout"><aside class="toc"><nav aria-label="{'章节目录' if zh else 'Contents'}"><h2>{'阅读目录' if zh else 'Contents'}</h2>{''.join(nav)}</nav></aside><main id="content">{''.join(body)}<footer><p><a href="{ref_url}">{refs}</a></p><p>{'截图为真实界面中的虚构教学数据，不是已审核论文结果。遇到科学问题请保留来源和疑点，与负责人核对。' if zh else 'Screenshots use fictional teaching data in the real UI, not approved paper results. Preserve sources and uncertainties and discuss scientific questions with your supervisor.'}</p></footer></main></div></body></html>
'''
    return html, '\n'.join(md)


def bundle_fonts(check):
    """Bundle licensed font shards used by either HTML, including offline readers."""
    package = ROOT / 'leadtrace/frontend/node_modules/@fontsource-variable/noto-sans-sc'
    glyphs = {ord(c) for lang in ('zh', 'en') for c in (PUBLIC / f'{lang}.html').read_text()}
    css = package / 'index.css'
    if not css.exists():
        raise SystemExit('Install frontend dependencies before regenerating/checking guide fonts')
    chosen = []
    for face in re.findall(r'@font-face\s*\{[^}]+\}', css.read_text()):
        ranges = re.search(r'unicode-range:\s*([^;]+)', face).group(1)
        matched = False
        for item in ranges.split(','):
            bounds = item.strip().removeprefix('U+').split('-')
            lo, hi = int(bounds[0], 16), int(bounds[-1], 16)
            if any(lo <= code <= hi for code in glyphs):
                matched = True
                break
        if not matched:
            continue
        name = re.search(r'url\(\./files/([^)]+)\)', face).group(1)
        source, target = package / 'files' / name, PUBLIC / 'fonts' / name
        if check:
            if not target.exists() or target.read_bytes() != source.read_bytes():
                raise SystemExit(f'Missing or changed bundled font: {name}')
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        chosen.append(face.replace('./files/', './fonts/'))
    font_css = '\n\n'.join(chosen) + '\n'
    for target, content in [(PUBLIC / 'fonts.css', font_css), (PUBLIC / 'fonts/LICENSE', (package / 'LICENSE').read_text())]:
        if check:
            if not target.exists() or target.read_text() != content:
                raise SystemExit(f'Stale guide font bundle: {target}')
        else:
            target.write_text(content)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    data = json.loads(SOURCE.read_text())
    ids = [s['id'] for s in data['sections']]
    if len(set(ids)) != len(ids):
        raise SystemExit('Duplicate guide section ID')
    PUBLIC.mkdir(parents=True, exist_ok=True)
    for lang in ('zh', 'en'):
        html, markdown = render(data, lang)
        for path, text in [(PUBLIC / f'{lang}.html', html), (DOCS / f'reviewer-guide.{lang}.md', markdown)]:
            if args.check:
                if not path.exists() or path.read_text() != text:
                    raise SystemExit(f'Stale generated guide: {path}')
            else:
                path.write_text(text)
        if args.check:
            for s in data['sections']:
                for b in s.get('blocks', []):
                    if b['type'] == 'figure' and not (PUBLIC / f'images/{b["asset"]}.{lang}.png').is_file():
                        raise SystemExit(f'Missing screenshot: {b["asset"]}.{lang}')
    bundle_fonts(args.check)
    print('Reviewer guides: consistent' if args.check else 'Reviewer HTML and Markdown generated')


if __name__ == '__main__':
    main()
