"""Export Markdown manuals to Word without extra runtime dependencies."""
from pathlib import Path
from xml.sax.saxutils import escape
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'


def paragraph(text, style='Normal'):
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'\1 (\2)', text).replace('**', '').replace('`', '')
    return f'<w:p><w:pPr><w:pStyle w:val="{style}"/></w:pPr><w:r><w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:p>'


def export(source, destination):
    content = []
    code = False
    for line in source.read_text(encoding='utf-8').splitlines():
        if line.startswith('```'):
            code = not code
            continue
        if line.startswith('|') and not code:
            cells = [cell.strip() for cell in line.strip('|').split('|')]
            if all(re.fullmatch(r'[-: ]+', cell) for cell in cells):
                continue
            line = '  |  '.join(cells)
        if line.startswith('# ') and not code:
            content.append(paragraph(line[2:], 'Title'))
        elif line.startswith('## ') and not code:
            content.append(paragraph(line[3:], 'Heading1'))
        elif line.startswith('### ') and not code:
            content.append(paragraph(line[4:], 'Heading2'))
        else:
            content.append(paragraph(line, 'Code' if code else 'Normal'))
    document = f'<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="{NS}"><w:body>' + ''.join(content) + '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134"/></w:sectPr></w:body></w:document>'
    styles = f'<w:styles xmlns:w="{NS}"><w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:eastAsia="Microsoft YaHei"/><w:sz w:val="21"/></w:rPr></w:rPrDefault></w:docDefaults>'
    for name, size in [('Normal',21),('Title',34),('Heading1',28),('Heading2',24),('Code',18)]:
        styles += f'<w:style w:type="paragraph" w:styleId="{name}"><w:name w:val="{name}"/><w:pPr><w:spacing w:after="100"/>' + ('<w:keepNext/>' if name.startswith('Heading') else '') + f'</w:pPr><w:rPr><w:sz w:val="{size}"/>' + ('<w:b/>' if name in {'Title','Heading1','Heading2'} else '') + '</w:rPr></w:style>'
    styles += '</w:styles>'
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>')
        z.writestr('_rels/.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        z.writestr('word/_rels/document.xml.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
        z.writestr('word/document.xml', document)
        z.writestr('word/styles.xml', styles)
    print(destination)


if __name__ == '__main__':
    export(ROOT / 'docs/OPERATOR_MANUAL.zh-CN.md', ROOT / 'docs/视频EEG_详细操作说明.docx')
    export(ROOT / 'docs/EXPERIMENT_DESCRIPTION.zh-CN.md', ROOT / 'docs/视频EEG_实验说明.docx')
