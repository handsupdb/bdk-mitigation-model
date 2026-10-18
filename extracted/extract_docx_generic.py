"""Generic docx -> text extractor reusing extract_mitigation_model functions.

Usage: .venv/bin/python extracted/extract_docx_generic.py <src.docx> <out.txt>
"""
import sys
import os
import zipfile
import re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from extract_mitigation_model import extract_docxml


def main():
    src, out = sys.argv[1], sys.argv[2]
    z = zipfile.ZipFile(src)
    names = z.namelist()

    lines = ['===== SOURCE: %s =====' % os.path.basename(src)]

    doc_data = z.read('word/document.xml')
    lines.append('[meta] m:oMath occurrences in document.xml: %d'
                 % doc_data.count(b'<m:oMath'))
    lines.append('[meta] w:drawing occurrences: %d'
                 % doc_data.count(b'<w:drawing'))
    lines.append('[meta] a:blip (image refs): %d'
                 % doc_data.count(b'<a:blip'))
    lines.append('')
    lines.extend(extract_docxml(doc_data))

    hf = [n for n in names if re.match(r'word/(header|footer)\d*\.xml$', n)]
    for n in sorted(hf):
        data = z.read(n)
        txts = [l for l in extract_docxml(data) if l.strip()]
        lines.append('')
        lines.append('===== %s =====' % n)
        lines.extend(txts if txts else ['(no text)'])

    media = [n for n in names if n.startswith('word/media/')]
    lines.append('')
    lines.append('===== MEDIA FILES =====')
    if media:
        for n in sorted(media):
            info = z.getinfo(n)
            lines.append('%s (%d bytes) [image - not OCRed]' % (n, info.file_size))
    else:
        lines.append('(none)')

    with open(out, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    print('Wrote %s: %d lines, %d words'
          % (out, len(lines), len(' '.join(lines).split())))


if __name__ == '__main__':
    main()
