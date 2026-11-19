#!/usr/bin/env python3
"""Synthetic regression test; no user PDFs or network calls."""
import argparse
from argparse import Namespace
import json
from pathlib import Path
import tempfile
import unicodedata

import fitz
import pdf_localize as helper


def run(regular, bold):
    with tempfile.TemporaryDirectory(prefix='pdf-skill-test-') as tmp:
        root = Path(tmp)
        source, output, manifest = root/'source.pdf', root/'translated.pdf', root/'patches.json'
        doc = fitz.open()
        first = doc.new_page(width=600, height=400)
        first.insert_text((50, 60), 'Replace this entire sentence.', fontsize=11)
        first.draw_rect(fitz.Rect(45, 35, 360, 95), color=(0, .5, 0), width=2)
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 4, 4), 0)
        pix.set_rect(pix.irect, (80, 160, 200))
        first.insert_image(fitz.Rect(420, 50, 520, 150), stream=pix.tobytes('png'))
        second = doc.new_page(width=600, height=400)
        second.insert_text((100, 200), 'Vertical placeholder', rotate=90, fontsize=11)
        second.set_rotation(90)
        doc[0].insert_link({'kind': fitz.LINK_URI, 'from': fitz.Rect(50, 45, 250, 70),
                            'uri': 'https://example.com/manual'})
        doc[0].insert_link({'kind': fitz.LINK_GOTO, 'from': fitz.Rect(50, 120, 200, 145),
                            'page': 1, 'to': fitz.Point(100, 120)})
        doc[1].insert_link({'kind': fitz.LINK_URI, 'from': fitz.Rect(85, 60, 110, 205),
                            'uri': 'https://example.com/rotated'})
        doc.set_toc([[1, 'First page', 1], [1, 'Second page', 2]])
        doc.save(source)
        doc.close()
        original_hash = helper.sha256(source)
        patches = [
            {'id': '1:body', 'page': 1,
             'text': 'Radar Warning Receiver（雷达告警接收机）\n检查全部条件与操作步骤。',
             'erase_rects': [[45, 35, 360, 95]], 'box': [50, 40, 355, 90],
             'font_size': 11, 'min_font_size': 8},
            {'id': '2:vertical', 'page': 2, 'text': 'Vertical（竖排文字）',
             'erase_rects': [[85, 60, 110, 205]], 'box': [85, 60, 110, 205],
             'font_size': 10.5, 'min_font_size': 8, 'rotate': 90, 'bold': True}
        ]
        helper.write_json(manifest, patches)
        args = Namespace(pdf=str(source), out=str(output), manifest=str(manifest),
                         font_regular=regular, font_bold=bold)
        helper.apply(args)
        with fitz.open(source) as before, fitz.open(output) as after:
            assert len(after) == 2
            assert after[1].rotation == 90
            assert 'Replace this entire' not in after[0].get_text()
            assert '雷达告警接收机' in unicodedata.normalize('NFKC', after[0].get_text()).replace('\n', ''), repr(after[0].get_text())
            assert 'Vertical placeholder' not in after[1].get_text()
            def toc_signature(pdf):
                return [(row[:3], {k: v for k, v in row[3].items() if k != 'xref'})
                        for row in pdf.get_toc(False)]
            assert toc_signature(before) == toc_signature(after)
            def drawing_signature(page):
                return [{k: v for k, v in drawing.items() if k != 'seqno'}
                        for drawing in page.get_drawings()]
            assert drawing_signature(before[0]) == drawing_signature(after[0])
            for i in range(2):
                assert helper.image_signature(before[i]) == helper.image_signature(after[i])
                assert helper.link_signature(before[i]) == helper.link_signature(after[i])
            assert before[0].get_image_info(hashes=True)[0]['digest'] == after[0].get_image_info(hashes=True)[0]['digest']
        code = helper.audit(Namespace(pdf=str(output), reference=str(source),
                                      out=str(root/'audit.json'), chinese_font_family='SourceHanSansSC'))
        assert code == 0
        assert json.loads((root/'audit.json').read_text())['semantic_review'] == 'NOT_ASSESSED'
        # Reject content loss/illegible auto-shrink before producing an output.
        patches[0]['box'] = [50, 40, 51, 41]
        helper.write_json(manifest, patches)
        args.out = str(root/'must_not_exist.pdf')
        try:
            helper.apply(args)
        except ValueError:
            pass
        else:
            raise AssertionError('An impossible text box must fail.')
        assert not Path(args.out).exists()
        helper.inspect(Namespace(pdf=str(source), out=str(root/'inventory.json')))
        helper.extract(Namespace(pdf=str(source), out=str(root/'extracted.json')))
        assert json.loads((root/'inventory.json').read_text())['pages'] == 2
        assert all(row['status'] == 'unreviewed_extraction'
                   for row in json.loads((root/'extracted.json').read_text()))
        helper.write_json(root/'units.json', [
            {'id': '1:review', 'page': 1, 'source': 'Original source', 'zh': '原有译文'}])
        helper.batches(Namespace(units=str(root/'units.json'), out_dir=str(root/'batches'),
                                 max_chars=1000))
        ledger = json.loads((root/'batches/ledger.json').read_text())
        assert ledger[0]['semantic_review'] == 'pending'
        assert helper.sha256(source) == original_hash
        print('PASS: Chinese text, rotated page, vector border, image bytes, URI/GOTO links, '
              'bookmark destinations and source hash retained; overflow rejected.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--font-regular', required=True)
    parser.add_argument('--font-bold', required=True)
    args = parser.parse_args()
    run(args.font_regular, args.font_bold)
