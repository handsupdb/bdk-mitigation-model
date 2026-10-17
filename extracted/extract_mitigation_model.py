"""Extract text from mitigation_model_support.docx using stdlib only."""
import zipfile
import xml.etree.ElementTree as ET
import os
import re

SRC = '/Users/dustinbyrtus/Documents/bdk_tools/mitigation_model_support.docx'
OUT = '/Users/dustinbyrtus/Documents/bdk_tools/extracted/docx_full.txt'

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
M = '{http://schemas.openxmlformats.org/officeDocument/2006/math}'


def para_text(p):
    """Linear text of a w:p, including OMML m:t, tabs, breaks."""
    parts = []
    for node in p.iter():
        tag = node.tag
        if tag == W + 't' or tag == M + 't':
            parts.append(node.text or '')
        elif tag == W + 'tab':
            parts.append('\t')
        elif tag in (W + 'br', W + 'cr'):
            parts.append(' / ')
    return ''.join(parts)


def para_style(p):
    pPr = p.find(W + 'pPr')
    if pPr is not None:
        pStyle = pPr.find(W + 'pStyle')
        if pStyle is not None:
            return pStyle.get(W + 'val', '')
    return ''


def table_lines(tbl):
    lines = []
    for tr in tbl.findall(W + 'tr'):
        cells = []
        for tc in tr.findall(W + 'tc'):
            cell_paras = [para_text(p) for p in tc.findall(W + 'p')]
            cells.append(' '.join(s.strip() for s in cell_paras if s.strip()))
        lines.append(' | '.join(cells))
    return lines


def extract_docxml(data):
    """Yield text lines from a word/*.xml document part, in body order."""
    out = []
    root = ET.fromstring(data)
    body = root.find(W + 'body')
    if body is None:
        body = root
    for child in body:
        tag = child.tag
        if tag == W + 'p':
            txt = para_text(child)
            style = para_style(child)
            if txt.strip():
                prefix = '[%s] ' % style if style else ''
                out.append(prefix + txt)
            else:
                out.append('')
        elif tag == W + 'tbl':
            out.append('[TABLE]')
            out.extend(table_lines(child))
            out.append('[/TABLE]')
        elif tag == M + 'oMathPara' or tag == M + 'oMath':
            # OMML equation as direct body child
            txt = ''.join(n.text or '' for n in child.iter(M + 't'))
            out.append('[OMML] ' + txt)
    return out


def main():
    z = zipfile.ZipFile(SRC)
    names = z.namelist()
    print('ZIP entries:', len(names))
    for n in names:
        print('  ', n)

    lines = []
    lines.append('===== SOURCE: %s =====' % os.path.basename(SRC))

    # main document
    doc_data = z.read('word/document.xml')
    omml_count = doc_data.count(b'<m:oMath')
    lines.append('[meta] m:oMath occurrences in document.xml: %d' % omml_count)
    lines.append('[meta] w:drawing occurrences: %d' % doc_data.count(b'<w:drawing'))
    lines.append('[meta] a:blip (image refs): %d' % doc_data.count(b'<a:blip'))
    lines.append('')
    lines.extend(extract_docxml(doc_data))

    # headers / footers
    hf = [n for n in names if re.match(r'word/(header|footer)\d*\.xml$', n)]
    for n in sorted(hf):
        data = z.read(n)
        txts = [l for l in extract_docxml(data) if l.strip()]
        lines.append('')
        lines.append('===== %s =====' % n)
        lines.extend(txts if txts else ['(no text)'])

    # media inventory
    media = [n for n in names if n.startswith('word/media/')]
    lines.append('')
    lines.append('===== MEDIA FILES =====')
    if media:
        for n in sorted(media):
            info = z.getinfo(n)
            lines.append('%s (%d bytes) [image - not OCRed]' % (n, info.file_size))
    else:
        lines.append('(none)')

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')

    nwords = len(' '.join(lines).split())
    print('Wrote %s: %d lines, %d words' % (OUT, len(lines), nwords))


if __name__ == '__main__':
    main()
