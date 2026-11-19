#!/usr/bin/env python3
"""Local PDF helpers. Translation, alignment and semantic review remain agent tasks."""
import argparse
import collections
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile

import fitz
from fontTools.ttLib import TTFont


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def jsonable(value):
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, fitz.Point, fitz.Rect)):
        return [jsonable(v) for v in value]
    return value


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(jsonable(data), ensure_ascii=False, indent=2), encoding='utf-8')


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def image_signature(page):
    return sorted((v['width'], v['height'], tuple(round(x, 3) for x in v['bbox']))
                  for v in page.get_image_info())


def link_signature(page):
    # Keep every returned destination field, including remote-file/named links.
    rows = [{k: v for k, v in x.items() if k not in ('xref', 'id')}
            for x in page.get_links()]
    return sorted(json.dumps(jsonable(x), sort_keys=True) for x in rows)


def bookmark_signature(doc):
    return [json.dumps(jsonable({'level': row[0], 'page': row[2],
                                'destination': {k: v for k, v in row[3].items()
                                                if k != 'xref'}}), sort_keys=True)
            for row in doc.get_toc(False)]


def inspect(args):
    path = Path(args.pdf)
    with fitz.open(path) as doc:
        pages = []
        for page in doc:
            pages.append({'page': page.number + 1, 'mediabox': list(page.mediabox),
                          'cropbox': list(page.cropbox), 'rotation': page.rotation,
                          'display_rect': list(page.rect),
                          'images': image_signature(page),
                          'links': page.get_links(),
                          'annotations': sum(1 for _ in (page.annots() or [])),
                          'fonts': page.get_fonts()})
        write_json(args.out, {'path': str(path.resolve()), 'sha256': sha256(path),
                              'pages': len(doc), 'bookmarks': doc.get_toc(False),
                              'page_inventory': pages})


def extract(args):
    """Extract raw page blocks; do not assert that a PDF block is a semantic unit."""
    rows = []
    with fitz.open(args.pdf) as doc:
        for page in doc:
            for index, block in enumerate(page.get_text('dict')['blocks']):
                if block['type'] != 0:
                    continue
                rows.append({'id': f'{page.number + 1}:{index}', 'page': page.number + 1,
                             'rect': block['bbox'], 'lines': block['lines'],
                             'text': '\n'.join(''.join(s['text'] for s in line['spans'])
                                              for line in block['lines']),
                             'rotation': page.rotation,
                             'status': 'unreviewed_extraction'})
    write_json(args.out, rows)


def batches(args):
    units = load_json(args.units)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    # Refuse to mix a new batch series with an existing review ledger.
    if any(out.glob('batch_*.txt')):
        raise ValueError('Batch files already exist; choose a new output directory.')
    chunks, text, ids = [], '', []
    for unit in units:
        entry = (f"ID: {unit['id']} | PAGE: {unit['page']} | STATUS: "
                 f"{unit.get('status', 'unreviewed')}\nEN: {unit['source']}\n"
                 f"ZH: {unit.get('zh', '')}\n\n")
        if text and len(text) + len(entry) > args.max_chars:
            chunks.append((text, ids))
            text, ids = '', []
        text += entry
        ids.append(unit['id'])
    if text:
        chunks.append((text, ids))
    for i, (text, ids) in enumerate(chunks, 1):
        (out / f'batch_{i:03d}.txt').write_text(text, encoding='utf-8')
        write_json(out / f'batch_{i:03d}_ids.json', ids)
    write_json(out / 'ledger.json', [{'batch': i, 'unit_ids': ids,
                                      'semantic_review': 'pending', 'issues': []}
                                     for i, (_, ids) in enumerate(chunks, 1)])
    print(f'Created {len(chunks)} batches; review status remains pending.')


def checked_rect(value, label):
    if not isinstance(value, list) or len(value) != 4 or not all(
            isinstance(v, (int, float)) and math.isfinite(v) for v in value):
        raise ValueError(f'{label}: expected four finite coordinates')
    rect = fitz.Rect(value)
    if rect.is_empty or rect.is_infinite:
        raise ValueError(f'{label}: invalid rectangle')
    return rect


def wrap_text(text, font, size, width):
    """CJK character wrapping, Latin word wrapping, attached closing punctuation."""
    result = []
    for para in text.split('\n'):
        tokens = re.findall(r'[A-Za-z0-9]+(?:[./_+–—−-][A-Za-z0-9]+)*|[^A-Za-z0-9]', para)
        atoms = []
        for token in tokens:
            if token in '，。；：！？、）】》〉,.!?:;)]' and atoms:
                atoms[-1] += token
            elif atoms and atoms[-1] in '（【《〈([':
                atoms[-1] += token
            else:
                atoms.append(token)
        line, used = '', 0.0
        for atom in atoms:
            advance = font.text_length(atom, fontsize=size)
            if advance > width:
                # Long identifiers can be broken; never silently clip a token.
                for char in atom:
                    step = font.text_length(char, fontsize=size)
                    if step > width:
                        raise ValueError('Text box is narrower than one glyph.')
                    if line and used + step > width:
                        result.append(line.rstrip())
                        line, used = '', 0.0
                    line += char
                    used += step
                continue
            if line and used + advance > width:
                result.append(line.rstrip())
                line, used = '', 0.0
                if atom.isspace():
                    continue
            line += atom
            used += advance
        result.append(line.rstrip())
    return result


def plan_patches(doc, manifest, font_paths):
    fonts = {bold: fitz.Font(fontfile=str(path)) for bold, path in font_paths.items()}
    cmaps = {}
    for bold, path in font_paths.items():
        with TTFont(path) as font:
            cmaps[bold] = font.getBestCmap() or {}
    prepared, seen = [], set()
    for item in manifest:
        uid = item['id']
        if uid in seen:
            raise ValueError(f'Duplicate patch ID: {uid}')
        seen.add(uid)
        pn = item['page']
        if not isinstance(pn, int) or not 1 <= pn <= len(doc):
            raise ValueError(f'{uid}: invalid one-based page number')
        if not isinstance(item.get('text'), str) or not item['text'].strip():
            raise ValueError(f'{uid}: empty translation is not a valid replacement')
        if any(c in item['text'] for c in ('\t', '\r')):
            raise ValueError(f'{uid}: use explicit spaces and LF newlines')
        box = checked_rect(item['box'], uid)
        page_box = fitz.Rect(0, 0, doc[pn - 1].cropbox.width, doc[pn - 1].cropbox.height)
        if not page_box.contains(box):
            raise ValueError(f'{uid}: box is outside the unrotated page area')
        erases = [checked_rect(v, uid) for v in item['erase_rects']]
        if not erases or not all(page_box.contains(v) for v in erases):
            raise ValueError(f'{uid}: erase rectangles must be explicit and on-page')
        rotation = item.get('rotate', 0)
        if rotation not in (0, 90, 180, 270):
            raise ValueError(f'{uid}: only orthogonal text rotations are supported')
        color = item.get('color', [0, 0, 0])
        if len(color) != 3 or not all(0 <= c <= 1 for c in color):
            raise ValueError(f'{uid}: color must be three RGB values from 0 to 1')
        size = float(item['font_size'])
        minimum = float(item.get('min_font_size', 8))
        if not 0 < minimum <= size:
            raise ValueError(f'{uid}: invalid font size limits')
        bold = bool(item.get('bold', False))
        missing = sorted({c for c in item['text'] if c != '\n' and ord(c) not in cmaps[bold]})
        if missing:
            raise ValueError(f'{uid}: font missing characters {missing[:20]!r}')
        width, height = ((box.height, box.width) if rotation in (90, 270)
                         else (box.width, box.height))
        while True:
            lines = wrap_text(item['text'], fonts[bold], size, width)
            if size * (1 + 1.08 * (len(lines) - 1)) <= height + 0.001:
                break
            if size <= minimum:
                raise ValueError(f'{uid}: cannot fit at minimum {minimum} pt; revise the layout')
            size = max(minimum, size * .97)
        prepared.append({**item, 'box': box, 'erase_rects': erases, 'rotate': rotation,
                         'color': color, 'bold': bold, 'actual_font_size': size, 'lines': lines})
    return prepared


def remove_text_only(page, rectangles):
    # Character centres avoid erasing adjacent lines whose font bounding boxes overlap.
    strips = collections.defaultdict(list)
    for block in page.get_text('rawdict')['blocks']:
        if block['type'] != 0:
            continue
        for line in block['lines']:
            horizontal = abs(line['dir'][0]) > .5
            for span in line['spans']:
                for char in span['chars']:
                    rect = fitz.Rect(char['bbox'])
                    center = fitz.Point((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2)
                    if not any(r.contains(center) for r in rectangles):
                        continue
                    if horizontal:
                        r = fitz.Rect(rect.x0 + .01, center.y - .1, rect.x1 - .01, center.y + .1)
                        key = ('h', round(r.y0, 2), round(r.y1, 2))
                    else:
                        r = fitz.Rect(center.x - .1, rect.y0 + .01, center.x + .1, rect.y1 - .01)
                        key = ('v', round(r.x0, 2), round(r.x1, 2))
                    if not r.is_empty:
                        strips[key].append(r)
    if not strips:
        raise ValueError(f'Page {page.number + 1}: no text found in erase rectangles; inspect baseline')
    for key, rectangles in strips.items():
        rectangles.sort(key=lambda r: r.x0 if key[0] == 'h' else r.y0)
        merged = rectangles[0]
        for rect in rectangles[1:]:
            gap = rect.x0 - merged.x1 if key[0] == 'h' else rect.y0 - merged.y1
            if gap < .5:
                merged |= rect
            else:
                page.add_redact_annot(merged, fill=False, cross_out=False)
                merged = rect
        page.add_redact_annot(merged, fill=False, cross_out=False)
    links = page.get_links()
    for link in links:
        page.delete_link(link)
    page.apply_redactions(images=0, graphics=0)
    for link in links:
        page.insert_link({k: v for k, v in link.items() if k not in ('xref', 'id')})


def apply(args):
    source, target = Path(args.pdf).resolve(), Path(args.out).resolve()
    if source == target or target.exists():
        raise ValueError('Output must be a new file; input and existing outputs are never overwritten.')
    font_paths = {False: Path(args.font_regular), True: Path(args.font_bold)}
    fitz.TOOLS.set_small_glyph_heights(True)
    manifest = load_json(args.manifest)
    if not isinstance(manifest, list) or not manifest:
        raise ValueError('Manifest must be a nonempty array.')
    with fitz.open(source) as doc:
        prepared = plan_patches(doc, manifest, font_paths)  # All fit/font checks before edits.
        # Canonical link coordinates during editing; restore every original rotation before saving.
        rotations = [page.rotation for page in doc]
        for page in doc:
            page.set_rotation(0)
        grouped = collections.defaultdict(list)
        for item in prepared:
            grouped[item['page']].append(item)
        report = []
        for pn, items in sorted(grouped.items()):
            page = doc[pn - 1]
            before_images, before_links = image_signature(page), link_signature(page)
            if any(a.type[0] == fitz.PDF_ANNOT_REDACT for a in (page.annots() or [])):
                raise ValueError(f'Page {pn} has unrelated pending redaction annotations.')
            remove_text_only(page, [r for item in items for r in item['erase_rects']])
            for item in items:
                size, box, rotation = item['actual_font_size'], item['box'], item['rotate']
                name = 'LocalizationBold' if item['bold'] else 'LocalizationRegular'
                page.insert_font(fontname=name, fontfile=str(font_paths[item['bold']]))
                for index, line in enumerate(item['lines']):
                    offset = size * (.88 + index * 1.08)
                    point = {0: (box.x0, box.y0 + offset),
                             90: (box.x0 + offset, box.y1),
                             180: (box.x1, box.y1 - offset),
                             270: (box.x1 - offset, box.y0)}[rotation]
                    page.insert_text(point, line, fontname=name, fontsize=size,
                                     color=item['color'], rotate=rotation)
                report.append({'id': item['id'], 'page': pn, 'font_size': size,
                               'box': list(box), 'lines': item['lines']})
            # Refresh link caches after delete/insert before comparing.
            page = doc.reload_page(page)
            if image_signature(page) != before_images or link_signature(page) != before_links:
                raise ValueError(f'Page {pn}: image geometry or link destinations changed')
        for index, rotation in enumerate(rotations):
            doc[index].set_rotation(rotation)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix='.localization-', suffix='.pdf', dir=target.parent)
        os.close(fd)
        os.unlink(tmp)
        try:
            doc.save(tmp, garbage=3, deflate=True, clean=True)
            os.replace(tmp, target)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
    write_json(str(target) + '.layout.json', report)
    print(f'Created {target}; {len(report)} text blocks. Semantic/visual review still required.')


def normalized_font(name):
    return re.sub(r'[^a-z0-9]', '', name.lower())


def audit(args):
    path = Path(args.pdf)
    with fitz.open(path) as doc:
        ref = fitz.open(args.reference) if args.reference else None
        try:
            issues, counts, fonts = [], collections.Counter(), set()
            if ref is not None and len(ref) != len(doc):
                issues.append({'type': 'page_count', 'expected': len(ref), 'actual': len(doc)})
            for page in doc:
                pn = page.number + 1
                links = page.get_links()
                counts.update(link['kind'] for link in links)
                for link in links:
                    if link['kind'] == fitz.LINK_GOTO and not 0 <= link.get('page', -1) < len(doc):
                        issues.append({'type': 'invalid_goto', 'page': pn})
                    if link['kind'] == fitz.LINK_URI and not link.get('uri'):
                        issues.append({'type': 'empty_uri', 'page': pn})
                for block in page.get_text('dict')['blocks']:
                    if block['type'] != 0:
                        continue
                    for line in block['lines']:
                        for span in line['spans']:
                            fonts.add(span['font'])
                            if re.search(r'[\u3400-\u9fff\uf900-\ufaff]', span['text']):
                                if normalized_font(args.chinese_font_family) not in normalized_font(span['font']):
                                    issues.append({'type': 'chinese_font', 'page': pn,
                                                   'font': span['font'], 'text': span['text'][:80]})
                if re.search(r'<unk>|⁇|待翻译|翻译失败', page.get_text()):
                    issues.append({'type': 'placeholder_candidate', 'page': pn})
                if ref is not None and page.number < len(ref):
                    old = ref[page.number]
                    if (list(page.mediabox), list(page.cropbox), page.rotation) != (
                            list(old.mediabox), list(old.cropbox), old.rotation):
                        issues.append({'type': 'page_geometry', 'page': pn})
                    if image_signature(page) != image_signature(old):
                        issues.append({'type': 'image_geometry', 'page': pn})
                    if link_signature(page) != link_signature(old):
                        issues.append({'type': 'link_destination_difference', 'page': pn})
            toc = doc.get_toc()
            for level, title, pn in toc:
                if pn != -1 and not 1 <= pn <= len(doc):
                    issues.append({'type': 'bookmark_target', 'title': title, 'page': pn})
            if ref is not None and bookmark_signature(doc) != bookmark_signature(ref):
                issues.append({'type': 'bookmark_destination_or_level_difference'})
            report = {'path': str(path.resolve()), 'sha256': sha256(path), 'pages': len(doc),
                      'bookmarks': len(toc), 'links_by_kind': dict(counts), 'fonts': sorted(fonts),
                      'issues': issues, 'automated_structure_check_passed': not issues,
                      'semantic_review': 'NOT_ASSESSED', 'visual_review': 'NOT_ASSESSED',
                      'limitations': 'Image geometry is checked; image bytes, vectors, formulas and translation meaning are not verified.'}
            write_json(args.out, report)
            print(f'{len(issues)} structural/font/placeholder issues; semantics not assessed.')
            return 0 if not issues else 2
        finally:
            if ref is not None:
                ref.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name, function in [('inspect', inspect), ('extract', extract)]:
        p = commands.add_parser(name)
        p.add_argument('--pdf', required=True)
        p.add_argument('--out', required=True)
        p.set_defaults(function=function)
    p = commands.add_parser('batches')
    p.add_argument('--units', required=True)
    p.add_argument('--out-dir', required=True)
    p.add_argument('--max-chars', type=int, default=24000)
    p.set_defaults(function=batches)
    p = commands.add_parser('apply')
    p.add_argument('--pdf', required=True)
    p.add_argument('--manifest', required=True)
    p.add_argument('--font-regular', required=True)
    p.add_argument('--font-bold', required=True)
    p.add_argument('--out', required=True)
    p.set_defaults(function=apply)
    p = commands.add_parser('audit')
    p.add_argument('--pdf', required=True)
    p.add_argument('--reference')
    p.add_argument('--out', required=True)
    p.add_argument('--chinese-font-family', default='SourceHanSansSC')
    p.set_defaults(function=audit)
    args = parser.parse_args()
    try:
        result = args.function(args)
        return result if isinstance(result, int) else 0
    except (ValueError, KeyError, OSError) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
