import os
import re
import sys

import img2pdf
import requests
from PIL import Image
from bs4 import BeautifulSoup
from tqdm import tqdm

BASE_URL = "https://opac.biblioteca.ase.ro"
SEARCH_URL = f"{BASE_URL}/opac/search"
BIBLIO_URL = f"{BASE_URL}/opac/bibliographic_view"
PAGE_SERVICE_URL = f"{BASE_URL}/fullTextPageService.svc"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

PAGE_INDEX_RE = re.compile(r"pageCount\s*=\s*(\d+)")

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def http_get(url, **kwargs):
    response = SESSION.get(url, **kwargs)
    response.raise_for_status()
    return response


def parse_description_page_count(description_text):
    if not description_text:
        return None
    match = re.search(r"([IVXLCDM]+)\s*,\s*(\d+)\s*p", description_text, re.IGNORECASE)
    if match:
        roman = match.group(1).upper()
        arabic = match.group(2)
        total = roman_to_int(roman) + int(arabic) if roman_to_int(roman) else int(arabic)
        return total
    match = re.search(r"(\d+)\s*p\b", description_text, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return None


def roman_to_int(roman):
    roman_values = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    roman = roman.upper()
    if not all(c in roman_values for c in roman):
        return 0
    total = 0
    prev = 0
    for char in reversed(roman):
        value = roman_values[char]
        if value < prev:
            total -= value
        else:
            total += value
        prev = value
    return total


def search_books(query, page=0):
    params = {"q": query, "start": page * 10, "view": "CONTENT"}
    response = http_get(SEARCH_URL, params=params)
    soup = BeautifulSoup(response.text, "html.parser")

    books = []
    seen = set()
    for head in soup.find_all("li", class_="reslt_item_head"):
        link = head.find("a", attrs={"name": "book_link"})
        if not link:
            continue
        href = link.get("href", "")
        match = re.search(r"/opac/bibliographic_view/(\d+)", href)
        if not match:
            continue
        book_id = match.group(1)
        if book_id in seen:
            continue
        seen.add(book_id)
        title = link.get("title") or link.get_text(strip=True)
        if title:
            title = re.sub(r"\s+", " ", title).strip()
        if not title:
            continue
        books.append({"id": book_id, "title": title, "href": href})
    return books


def prompt_book_selection(books):
    print(f"\nFound {len(books)} result(s):\n")
    for idx, book in enumerate(books, start=1):
        print(f"  [{idx:>3}] {book['title']}")
    print()
    while True:
        choice = input("Select a book by number (or 'q' to quit): ").strip()
        if choice.lower() in {"q", "quit", "exit"}:
            print("Aborted.")
            sys.exit(0)
        if choice.isdigit():
            index = int(choice) - 1
            if 0 <= index < len(books):
                return books[index]
        print("Invalid selection, please try again.")


def fetch_bibliographic_view(book_id):
    response = http_get(f"{BIBLIO_URL}/{book_id}")
    return BeautifulSoup(response.text, "html.parser")


def extract_record_details(soup):
    record = soup.find(id="record_details")
    if not record:
        return None
    info = {}
    rows = record.find_all("tr")
    label_to_key = {
        "titlu": "title",
        "autor": "author",
        "editura": "publisher",
        "descriere": "description",
        "isbn": "isbn",
        "cota": "call_number",
        "ediție": "edition",
    }
    for row in rows:
        header = row.find("th")
        cell = row.find("td")
        if not header or not cell:
            continue
        label = header.get_text(strip=True).rstrip(":").lower()
        value = re.sub(r"\s+", " ", cell.get_text(" ", strip=True)).strip()
        for key, target in label_to_key.items():
            if label.startswith(key):
                info[target] = value
                break
    return info or None


def extract_multimedia_subsections(soup):
    multimedia = soup.find(id="multimediaArea")
    if not multimedia:
        return []

    parent = multimedia.parent
    if parent is None:
        return []

    subsections = []
    current_title = None
    current_select = None
    pending_selects = []

    for element in parent.find_all_next():
        if element.get("id") == "multimediaArea":
            continue
        if element.get("id") == "reviewsTab":
            break

        if element.name == "div":
            em = element.find("em", class_="expand-em", recursive=False)
            if em and not em.get("id"):
                title = re.sub(r"\s+", " ", em.get_text(" ", strip=True)).strip()
                if title:
                    current_title = title
                    current_select = None

        if element.name == "select" and element.get("id", "").startswith("docSelection_"):
            if current_title is not None:
                subsections.append({"title": current_title, "select": element})
                current_title = None
            else:
                pending_selects.append(element)

    for select in pending_selects:
        subsections.append({"title": "(unlabeled)", "select": select})

    options_per_section = []
    for section in subsections:
        select = section["select"]
        section_options = []
        for opt in select.find_all("option"):
            value = opt.get("value", "").strip()
            if not value.startswith("/fullTextPageService.svc?c="):
                continue
            label = re.sub(r"\s+", " ", opt.get_text(" ", strip=True)).strip()
            code = value.split("c=", 1)[1]
            section_options.append({"code": code, "label": label, "raw_url": value})
        if section_options:
            options_per_section.append({"title": section["title"], "options": section_options})

    return options_per_section


def fetch_page_count(code):
    url = f"{PAGE_SERVICE_URL}?c={code}&e=.js"
    try:
        response = http_get(url, timeout=15)
    except requests.RequestException:
        return None
    text = response.text.strip()
    if not text:
        return None
    match = PAGE_INDEX_RE.search(text)
    if not match:
        return None
    count = int(match.group(1))
    return count if count > 0 else None


def choose_best_subsection(record_info, subsections):
    target_pages = parse_description_page_count((record_info or {}).get("description", "")) if record_info else None

    candidates = []
    for section in subsections:
        for option in section["options"]:
            count = fetch_page_count(option["code"])
            if count is None:
                continue
            candidates.append({
                "section_title": section["title"],
                "option_label": option["label"],
                "code": option["code"],
                "page_count": count,
            })

    if not candidates:
        return target_pages, []

    if target_pages is None:
        chosen = candidates[0]
    else:
        chosen = min(candidates, key=lambda c: (abs(c["page_count"] - target_pages), -c["page_count"]))

    print("\nAvailable subsections:")
    print(f"  Target page count (from description): {target_pages}")
    for candidate in candidates:
        marker = " <-- selected" if candidate is chosen else ""
        print(f"    - [{candidate['section_title']}] '{candidate['option_label']}' -> {candidate['page_count']} pages{marker}")
    return target_pages, chosen


def download_book(code, page_count, output_folder):
    os.makedirs(output_folder, exist_ok=True)
    print(f"\nDownloading {page_count} page(s) from {code}...")
    downloaded = 0
    bar = tqdm(range(page_count), unit="page", ncols=70)
    for page in bar:
        bar.set_description(f"page {page + 1}/{page_count}")
        url = f"{PAGE_SERVICE_URL}?c={code}&e=-{page}.png"
        file_name = os.path.join(output_folder, f"pagina_{page}.png")
        try:
            response = SESSION.get(url, stream=True, timeout=30)
        except requests.RequestException as exc:
            tqdm.write(f"  ! page {page} failed: {exc}")
            continue
        if response.status_code != 200:
            tqdm.write(f"  ! page {page} HTTP {response.status_code}")
            continue
        bytes_written = 0
        with open(file_name, "wb") as fh:
            for chunk in response.iter_content(1024):
                if chunk:
                    fh.write(chunk)
                    bytes_written += len(chunk)
        if bytes_written == 0:
            tqdm.write(f"  ! page {page} empty response, removing placeholder")
            try:
                os.remove(file_name)
            except OSError:
                pass
            continue
        downloaded += 1
    bar.close()
    return downloaded


def build_pdf(output_folder, output_pdf):
    image_files = sorted(
        (f for f in os.listdir(output_folder) if f.endswith(".png")),
        key=lambda x: int(x.split("_")[1].split(".")[0]),
    )
    if not image_files:
        print("No images found to convert.")
        return False

    print("\nBuilding PDF...")
    paths = [os.path.join(output_folder, f) for f in image_files]

    sanitized_dir = os.path.join(output_folder, "_sanitized")
    os.makedirs(sanitized_dir, exist_ok=True)
    sanitized_paths = []
    for path in paths:
        with Image.open(path) as img:
            img.load()
            needs_flatten = (
                img.mode in ("RGBA", "LA")
                or (img.mode == "P" and "transparency" in img.info)
            )
            if needs_flatten:
                base = Image.new("RGB", img.size, (255, 255, 255))
                if img.mode in ("RGBA", "LA"):
                    mask = img.split()[-1]
                    base.paste(img.convert("RGBA"), mask=mask)
                else:
                    rgba = img.convert("RGBA")
                    mask = rgba.split()[3]
                    base.paste(rgba, mask=mask)
                sanitized_img = base
            elif img.mode == "P":
                sanitized_img = img.convert("RGB")
            elif img.mode == "L":
                sanitized_img = img.convert("RGB")
            else:
                sanitized_img = img.convert("RGB") if img.mode != "RGB" else img
        sanitized_path = os.path.join(sanitized_dir, os.path.basename(path))
        sanitized_img.save(sanitized_path, format="PNG", optimize=False)
        sanitized_paths.append(sanitized_path)

    with open(output_pdf, "wb") as fh:
        fh.write(img2pdf.convert(sanitized_paths, layout_fun=img2pdf.default_layout_fun))
    print(f"PDF saved as {output_pdf}")

    try:
        for fname in os.listdir(sanitized_dir):
            os.remove(os.path.join(sanitized_dir, fname))
        os.rmdir(sanitized_dir)
    except OSError:
        pass
    return True


def run_search_mode():
    query = input("Search the library for a book (title/author/ISBN): ").strip()
    while not query:
        query = input("Search the library for a book (title/author/ISBN): ").strip()

    page = 0
    selected_book = None
    while selected_book is None:
        print(f"\nSearching for '{query}' (page {page + 1})...")
        try:
            books = search_books(query, page=page)
        except requests.RequestException as exc:
            print(f"Search failed: {exc}")
            return

        if not books:
            if page == 0:
                print("No results. Try a different query.")
                return
            print("No more results.")
            return

        books = books[:10]
        selected_book = prompt_book_selection(books)
        if selected_book is None:
            return

    print(f"\nLoading details for '{selected_book['title']}' (id={selected_book['id']})...")
    try:
        soup = fetch_bibliographic_view(selected_book["id"])
    except requests.RequestException as exc:
        print(f"Failed to load book page: {exc}")
        return

    record = extract_record_details(soup)
    if record:
        print("\nBook details:")
        for key in ("title", "author", "publisher", "edition", "description", "isbn"):
            value = record.get(key)
            if value:
                print(f"  {key.capitalize():<11}: {value}")

    subsections = extract_multimedia_subsections(soup)
    if not subsections:
        print("\nNo digital subsections found for this book.")
        return

    target_pages, chosen = choose_best_subsection(record, subsections)
    if chosen is None:
        print("\nNo subsection could be retrieved (likely restricted to the ASE intranet).")
        return

    default_pages = chosen["page_count"]
    prompt = f"Number of pages to download [default {default_pages}]: "
    user_input = input(prompt).strip()
    if user_input:
        if not user_input.isdigit() or int(user_input) <= 0:
            print("Invalid page count, aborting.")
            return
        page_count = int(user_input)
    else:
        page_count = default_pages

    default_pdf = (
        re.sub(r"[^\w\-]+", "_", record.get("title") if record and record.get("title") else selected_book["title"]).strip("_")
        or f"book_{selected_book['id']}"
    )
    output_pdf_name = input(f"Name of the PDF (without .pdf) [default {default_pdf}]: ").strip() or default_pdf
    output_pdf = output_pdf_name + ".pdf"

    output_folder = "pagini_carte"
    downloaded = download_book(chosen["code"], page_count, output_folder)
    if downloaded == 0:
        print("Could not download any pages. Aborting.")
        return

    build_pdf(output_folder, output_pdf)
    cleanup_png_folder(output_folder)


def run_code_mode():
    book_code = input("ASE book code: ").strip()
    while not book_code:
        book_code = input("ASE book code: ").strip()

    pages_input = input("Number of pages: ").strip()
    if not pages_input.isdigit() or int(pages_input) <= 0:
        print("Invalid page count, aborting.")
        return
    page_count = int(pages_input)

    default_pdf = re.sub(r"[^\w\-]+", "_", book_code).strip("_") or "book"
    pdf_input = input(f"Name of the PDF (without .pdf) [default {default_pdf}]: ").strip() or default_pdf
    output_pdf = pdf_input + ".pdf"

    output_folder = "pagini_carte"
    downloaded = download_book(book_code, page_count, output_folder)
    if downloaded == 0:
        print("Could not download any pages. Aborting.")
        return

    build_pdf(output_folder, output_pdf)
    cleanup_png_folder(output_folder)


def cleanup_png_folder(output_folder):
    try:
        for fname in os.listdir(output_folder):
            if fname.endswith(".png"):
                os.remove(os.path.join(output_folder, fname))
        os.rmdir(output_folder)
    except OSError:
        pass


def prompt_main_mode():
    print("=== ASE Library Book Downloader ===\n")
    print("  [1] Search the library for a book")
    print("  [2] Enter a book code directly")
    print()
    while True:
        choice = input("Choose an option [1/2] (or 'q' to quit): ").strip()
        if choice.lower() in {"q", "quit", "exit"}:
            print("Aborted.")
            sys.exit(0)
        if choice == "1":
            return "search"
        if choice == "2":
            return "code"
        print("Invalid choice, please type 1 or 2.")


def main():
    mode = prompt_main_mode()
    if mode == "search":
        run_search_mode()
    elif mode == "code":
        run_code_mode()


if __name__ == "__main__":
    main()
