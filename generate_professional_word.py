import os
import sys

def make_professional():
    input_md = "Laporan_Teknis_NusaRail_SourceCode.md"
    output_docx = "Laporan_Teknis_NusaRail_v3.docx"

    print("Mengonversi Markdown ke Word dengan pypandoc...")
    import pypandoc
    extra_args = [
        '--toc',
        '--number-sections',
        '-V', 'geometry:margin=1in',
    ]
    pypandoc.convert_file(input_md, 'docx', outputfile=output_docx, extra_args=extra_args)
    print("Konversi pypandoc selesai.")

    print("Membersihkan format (menghapus teks biru menjadi hitam pekat) dengan python-docx...")
    try:
        import docx
        from docx.shared import RGBColor
    except ImportError:
        os.system('pip install python-docx')
        import docx
        from docx.shared import RGBColor

    doc = docx.Document(output_docx)
    
    # Force all styles to be black
    for style in doc.styles:
        if hasattr(style, 'font'):
            if style.font.color:
                style.font.color.rgb = RGBColor(0, 0, 0)
    
    # Explicitly hit the known Word heading styles
    styles_to_fix = ['Title', 'Subtitle', 'Heading 1', 'Heading 2', 'Heading 3', 'Heading 4', 'Heading 5', 'TOC Heading']
    for s in styles_to_fix:
        try:
            style = doc.styles[s]
            if style.font:
                style.font.color.rgb = RGBColor(0, 0, 0)
        except KeyError:
            pass

    # Loop through all paragraphs and runs to forcefully strip local color overrides
    for para in doc.paragraphs:
        # Force paragraph style font color
        if para.style and para.style.font:
            para.style.font.color.rgb = RGBColor(0, 0, 0)
        for run in para.runs:
            if run.font and run.font.color and run.font.color.rgb:
                run.font.color.rgb = RGBColor(0, 0, 0)

    doc.save(output_docx)
    print(f"Berhasil! File akhir tersimpan di: {output_docx}")

if __name__ == "__main__":
    make_professional()
