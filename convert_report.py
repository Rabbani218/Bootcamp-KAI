import os
import sys

def convert_documents():
    print("Menginisialisasi konversi Laporan Teknis ke format Word (DOCX)...")
    
    # Check if pypandoc is installed
    try:
        import pypandoc
    except ImportError:
        print("Error: pypandoc tidak ditemukan.")
        sys.exit(1)
        
    # Download pandoc if not found
    try:
        pypandoc.get_pandoc_version()
    except OSError:
        print("Pandoc tidak ditemukan di sistem. Mengunduh Pandoc secara otomatis...")
        pypandoc.download_pandoc()
        print("Pandoc berhasil diunduh!")

    input_md = "Laporan_Teknis_NusaRail_SourceCode.md"
    output_docx = "Laporan_Teknis_NusaRail_v2.docx"
    output_pdf = "Laporan_Teknis_NusaRail_v2.pdf"

    if not os.path.exists(input_md):
        print(f"Error: File sumber {input_md} tidak ditemukan.")
        sys.exit(1)

    print(f"Mengonversi {input_md} ke {output_docx}...")
    
    # We use pandoc's native arguments to make it professional
    extra_args = [
        '--toc',  # Generate Table of Contents
        '--number-sections',  # Numbered headers
        '-V', 'geometry:margin=1in',
        '-V', 'mainfont=Arial'
    ]

    try:
        pypandoc.convert_file(
            input_md, 
            'docx', 
            outputfile=output_docx, 
            extra_args=extra_args
        )
        print(f"Berhasil! File Word tersimpan di: {output_docx}")
    except Exception as e:
        print(f"Gagal mengonversi ke DOCX: {e}")
        sys.exit(1)

    print("\nMencoba mengonversi DOCX ke PDF menggunakan docx2pdf...")
    try:
        from docx2pdf import convert
        convert(output_docx, output_pdf)
        print(f"Berhasil! File PDF tersimpan di: {output_pdf}")
    except Exception as e:
        print(f"Peringatan: Gagal mengonversi ke PDF secara otomatis (mungkin MS Word tidak terinstal/berjalan di background): {e}")

if __name__ == "__main__":
    convert_documents()
