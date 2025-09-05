import requests
from PIL import Image
import os

book_code=input("ASE book code: ")
book_pages=int(input("Number of pages: "))
output_folder = "pagini_carte"
output_pdf = input("Name of the pdf: ") + ".pdf"

base_url = "https://opac.biblioteca.ase.ro/fullTextPageService.svc?c={}&e=-{}.png"


os.makedirs(output_folder, exist_ok=True)

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

print("Downloading images...")
for i in range(book_pages):
    image_url = base_url.format(book_code,i)
    file_name = os.path.join(output_folder, f"pagina_{i}.png")
    
    print(f"Downloading {image_url}...")
    response = requests.get(image_url, headers=headers, stream=True)
    
    if response.status_code == 200:
        with open(file_name, 'wb') as file:
            for chunk in response.iter_content(1024):
                file.write(chunk)
        print(f"Saved: {file_name}")
    else:
        print(f"Failed to download {image_url}, code: {response.status_code}")

print("Download completed.")

print("Converting images to PDF...")
image_files = sorted([f for f in os.listdir(output_folder) if f.endswith(".png")], 
                    key=lambda x: int(x.split('_')[1].split('.')[0]))

if image_files:
    image_list = []
    first_image = Image.open(os.path.join(output_folder, image_files[0])).convert("RGB")
    
    for img_file in image_files[1:]:
        img = Image.open(os.path.join(output_folder, img_file)).convert("RGB")
        image_list.append(img)
    
    first_image.save(output_pdf, save_all=True, append_images=image_list)
    print(f"PDF saved as {output_pdf}")
else:
    print("No images found to convert.")