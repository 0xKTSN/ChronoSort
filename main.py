import os
import shutil
import hashlib
from datetime import datetime
from tkinter import (
    Tk,
    Label,
    Button,
    Entry,
    filedialog,
    StringVar,
    Checkbutton,
    BooleanVar,
)
from tqdm import tqdm

from PIL import Image
from PIL.ExifTags import TAGS
import imagehash


# --- Hash fichier (SHA256) ---
def get_file_hash(path):
    try:
        hasher = hashlib.sha256()
        with open(path, "rb") as f:
            while chunk := f.read(8192):
                hasher.update(chunk)
        return hasher.hexdigest()
    except:
        return None


# --- Hash visuel (images uniquement) ---
def get_image_phash(path):
    try:
        with Image.open(path) as img:
            return imagehash.phash(img)
    except:
        return None


# --- EXIF ---
def get_exif_date(path):
    try:
        image = Image.open(path)
        exif = image._getexif()

        if exif:
            for tag, value in exif.items():
                tag_name = TAGS.get(tag, tag)
                if tag_name in ["DateTimeOriginal", "DateTime"]:
                    return datetime.strptime(value, "%Y:%m:%d %H:%M:%S")
    except:
        pass
    return None


# --- fallback ---
def get_file_date(path):
    try:
        return datetime.fromtimestamp(os.path.getmtime(path))
    except:
        return None


# --- traitement ---
def process_files():
    source_dir = source_path.get()
    target_dir = target_path.get()
    move_files = move_var.get()

    if not os.path.exists(source_dir):
        status.set("Dossier source invalide")
        return

    os.makedirs(target_dir, exist_ok=True)

    # --- scan initial pour progress bar ---
    all_files = []
    for root, dirs, files in os.walk(source_dir):
        for f in files:
            all_files.append(os.path.join(root, f))

    print(f"Fichiers trouvés : {len(all_files)}")

    hashes_seen = {}
    image_hashes = []

    doublon_dir = os.path.join(target_dir, "Doublon")
    doublon_created = False

    for source_file in tqdm(all_files, desc="Traitement"):

        file_name = os.path.basename(source_file)

        # --- hash fichier ---
        file_hash = get_file_hash(source_file)

        # --- détection doublon exact ---
        is_duplicate = file_hash in hashes_seen if file_hash else False

        # --- détection visuelle (images uniquement) ---
        visual_duplicate = False
        phash = get_image_phash(source_file)

        if phash:
            for existing_hash in image_hashes:
                if abs(phash - existing_hash) <= 5:  # seuil tolérance
                    visual_duplicate = True
                    break

        # --- date ---
        date = get_exif_date(source_file)
        if date is None:
            date = get_file_date(source_file)

        date_str = date.strftime("%Y-%m-%d_%H-%M-%S") if date else "unknown_date"
        new_name = f"{date_str}_{file_name}"

        # --- choix destination ---
        if is_duplicate or visual_duplicate:
            if not doublon_created:
                os.makedirs(doublon_dir, exist_ok=True)
                doublon_created = True
                print("📁 Dossier Doublon créé")

            target_base = doublon_dir

            if is_duplicate:
                print(f"[DUPLICATE HASH] {file_name}")
            elif visual_duplicate:
                print(f"[DUPLICATE VISUEL] {file_name}")

        else:
            target_base = target_dir

        target_file = os.path.join(target_base, new_name)

        base, ext = os.path.splitext(new_name)
        counter = 1

        while os.path.exists(target_file):
            target_file = os.path.join(target_base, f"{base}_{counter}{ext}")
            counter += 1

        try:
            if move_files:
                shutil.move(source_file, target_file)
            else:
                shutil.copy2(source_file, target_file)

            print(f"[OK] {file_name} -> {target_file}")

        except Exception as e:
            print(f"[ERREUR] {file_name} : {e}")
            continue

        if file_hash:
            hashes_seen[file_hash] = target_file

        if phash:
            image_hashes.append(phash)

    # --- suppression dossiers vides ---
    for root, dirs, files in os.walk(source_dir, topdown=False):
        if not os.listdir(root):
            try:
                os.rmdir(root)
                print(f"[SUPPRIME] dossier vide : {root}")
            except:
                pass

    status.set("Terminé !")
    print("=== FIN ===")


# --- UI ---
app = Tk()
app.title("Tri avancé fichiers")

source_path = StringVar()
target_path = StringVar()
status = StringVar()
move_var = BooleanVar()

Label(app, text="Dossier source").pack()
Entry(app, textvariable=source_path, width=50).pack()
Button(
    app, text="Choisir", command=lambda: source_path.set(filedialog.askdirectory())
).pack()

Label(app, text="Dossier destination").pack()
Entry(app, textvariable=target_path, width=50).pack()
Button(
    app, text="Choisir", command=lambda: target_path.set(filedialog.askdirectory())
).pack()

Checkbutton(app, text="Déplacer (au lieu de copier)", variable=move_var).pack()

Button(app, text="Lancer", command=process_files).pack()

Label(app, textvariable=status).pack()

app.mainloop()
