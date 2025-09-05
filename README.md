# ASE Library Book Downloader

A Python script to download and convert book pages from the ASE (Academia de Studii Economice din București) digital library to PDF format.

## Features

- Downloads book pages from the ASE digital library
- Converts downloaded PNG images to a single PDF file
- Simple command-line interface
- Customizable output filename

## Requirements

- Python 3.x
- `requests` library
- `Pillow` library (PIL fork)

## Installation

1. Clone this repository or download the script
2. Install the required dependencies:

```bash
pip install requests Pillow
```

## Usage

1. Run the script:
```bash
python asedownload.py
```

2. Enter the required information when prompted:
   - ASE book code (found in the URL when viewing the book online)
   - Number of pages in the book
   - Name for the output PDF file

3. The script will:
   - Download all pages as PNG images to a `pagini_carte` folder
   - Convert the images to a single PDF file
   - Save the PDF with your specified name

## Example

```
ASE book code: ABC123
Number of pages: 250
Name of the pdf: My_ASE_Book
```

This will create `My_ASE_Book.pdf` containing all 250 pages.

## Notes

- This tool is intended for educational and personal use only
- Please respect the terms of use of the ASE digital library
- The script may need updates if the ASE website changes its API

## Disclaimer

This tool is not affiliated with or endorsed by Academia de Studii Economice din București. 
