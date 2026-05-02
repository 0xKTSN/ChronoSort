import os
import shutil
import hashlib
import threading
import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext
from datetime import datetime

from PIL import Image
from PIL.ExifTags import TAGS
import imagehash
import pybktree
from pypdf import PdfReader

# ─── Constantes ───────────────────────────────────────────────────────────────
CHUNK_SIZE              = 8192
DEFAULT_PHASH_THRESHOLD = 5  # 0 = identique strict · 10 = très permissif

SYSTEM_FILES = {
    ".DS_Store", "Thumbs.db", "desktop.ini",
    ".localized", ".Spotlight-V100", "ehthumbs.db",
}

# ─── Catégories et organisation ───────────────────────────────────────────────
# Valeur : (dossier_catégorie, sous_dossier_par_extension)
EXTENSION_CATEGORIES: dict[str, tuple[str, bool]] = {
    # Images
    ".jpg":  ("Images", True),  ".jpeg": ("Images", True),
    ".png":  ("Images", True),  ".gif":  ("Images", True),
    ".bmp":  ("Images", True),  ".tiff": ("Images", True),
    ".tif":  ("Images", True),  ".webp": ("Images", True),
    ".heic": ("Images", True),  ".heif": ("Images", True),
    ".raw":  ("Images", True),  ".cr2":  ("Images", True),
    ".nef":  ("Images", True),  ".arw":  ("Images", True),
    # Vidéos
    ".mp4":  ("Vidéos", True),  ".mov":  ("Vidéos", True),
    ".avi":  ("Vidéos", True),  ".mkv":  ("Vidéos", True),
    ".wmv":  ("Vidéos", True),  ".flv":  ("Vidéos", True),
    ".webm": ("Vidéos", True),  ".m4v":  ("Vidéos", True),
    ".3gp":  ("Vidéos", True),  ".mpg":  ("Vidéos", True),
    ".mpeg": ("Vidéos", True),
    # PDF
    ".pdf":  ("PDF", False),
    # Word
    ".doc":  ("Word", False),   ".docx": ("Word", False),
    ".odt":  ("Word", False),   ".rtf":  ("Word", False),
    # Excel
    ".xls":  ("Excel", False),  ".xlsx": ("Excel", False),
    ".ods":  ("Excel", False),  ".csv":  ("Excel", False),
    # PowerPoint
    ".ppt":  ("PowerPoint", False), ".pptx": ("PowerPoint", False),
    ".odp":  ("PowerPoint", False),
    # Audio
    ".mp3":  ("Audio", True),   ".wav":  ("Audio", True),
    ".flac": ("Audio", True),   ".aac":  ("Audio", True),
    ".ogg":  ("Audio", True),   ".wma":  ("Audio", True),
    ".m4a":  ("Audio", True),   ".opus": ("Audio", True),
    # Archives
    ".zip":  ("Archives", False), ".rar": ("Archives", False),
    ".7z":   ("Archives", False), ".tar": ("Archives", False),
    ".gz":   ("Archives", False), ".bz2": ("Archives", False),
}

IMAGE_EXTENSIONS = {k for k, (c, _) in EXTENSION_CATEGORIES.items() if c == "Images"}


def get_target_subfolder(file_path: str, target_dir: str) -> str:
    """Retourne le dossier de destination selon l'extension du fichier."""
    ext = os.path.splitext(file_path)[1].lower()
    if ext in EXTENSION_CATEGORIES:
        category, use_ext_subfolder = EXTENSION_CATEGORIES[ext]
        if use_ext_subfolder:
            return os.path.join(target_dir, category, ext.lstrip(".").upper())
        return os.path.join(target_dir, category)
    return os.path.join(target_dir, "Autres")


# ─── Hash fichier (SHA256) ─────────────────────────────────────────────────────
def get_file_hash(path: str) -> str | None:
    try:
        hasher = hashlib.sha256()
        with open(path, "rb") as f:
            while chunk := f.read(CHUNK_SIZE):
                hasher.update(chunk)
        return hasher.hexdigest()
    except Exception:
        return None


# ─── Hash visuel pHash (images) ───────────────────────────────────────────────
def get_image_phash(path: str):
    try:
        with Image.open(path) as img:
            return imagehash.phash(img)
    except Exception:
        return None


# ─── Hash textuel PDF ─────────────────────────────────────────────────────────
def get_pdf_text_hash(path: str) -> str | None:
    """
    Extrait le texte du PDF et retourne son hash SHA256.
    Retourne None si le PDF est scanné (pas de texte extractible).
    """
    try:
        reader = PdfReader(path)
        text = "".join(page.extract_text() or "" for page in reader.pages)
        if not text.strip():
            return None  # PDF scanné — fallback SHA256 uniquement
        return hashlib.sha256(text.encode("utf-8")).hexdigest()
    except Exception:
        return None


# ─── EXIF ──────────────────────────────────────────────────────────────────────
def get_exif_date(path: str) -> datetime | None:
    try:
        with Image.open(path) as image:
            exif = image.getexif()
            if exif:
                for tag, value in exif.items():
                    tag_name = TAGS.get(tag, tag)
                    if tag_name in ("DateTimeOriginal", "DateTime"):
                        return datetime.strptime(value, "%Y:%m:%d %H:%M:%S")
    except Exception:
        pass
    return None


# ─── Fallback date ─────────────────────────────────────────────────────────────
def get_file_date(path: str) -> datetime | None:
    try:
        return datetime.fromtimestamp(os.path.getmtime(path))
    except Exception:
        return None


# ─── Indexation de la destination existante ───────────────────────────────────
def index_existing_destination(
    target_dir:      str,
    phash_threshold: int,
    cancel_event:    threading.Event,
    on_log,
    on_progress,
) -> tuple[dict, dict, pybktree.BKTree, bool]:
    """
    Parcourt les fichiers déjà présents dans la destination et pré-remplit
    les structures de déduplication. Cela garantit qu'une nouvelle passe
    avec un dossier source différent ne produira pas de doublons par rapport
    aux fichiers déjà triés.

    Retourne : (hashes_seen, pdf_hashes_seen, phash_tree, tree_is_empty)
    """
    hashes_seen     = {}
    pdf_hashes_seen = {}
    phash_tree      = pybktree.BKTree(lambda a, b: abs(a - b))
    tree_is_empty   = True

    if not os.path.isdir(target_dir):
        return hashes_seen, pdf_hashes_seen, phash_tree, tree_is_empty

    existing_files = []
    for root, _, files in os.walk(target_dir):
        for f in files:
            if f in SYSTEM_FILES or f.startswith("."):
                continue
            existing_files.append(os.path.join(root, f))

    count = len(existing_files)

    if count == 0:
        on_log("📂 Destination vierge — aucun fichier existant à indexer.\n")
        return hashes_seen, pdf_hashes_seen, phash_tree, tree_is_empty

    on_log(f"🔍 Indexation de la destination : {count} fichier(s) déjà présent(s)…")
    on_log(   "   (Les doublons avec ces fichiers seront détectés même si la source change.)\n")

    indexed = 0
    for path in existing_files:
        if cancel_event.is_set():
            break

        ext = os.path.splitext(path)[1].lower()

        file_hash = get_file_hash(path)
        if file_hash:
            hashes_seen[file_hash] = path

        if ext in IMAGE_EXTENSIONS:
            phash = get_image_phash(path)
            if phash:
                phash_tree.add(phash)
                tree_is_empty = False

        if ext == ".pdf":
            pdf_text_hash = get_pdf_text_hash(path)
            if pdf_text_hash:
                pdf_hashes_seen[pdf_text_hash] = path

        indexed += 1
        on_progress(indexed, count, f"Indexation : {indexed} / {count}")

    on_log(f"✅ Indexation terminée — {indexed} fichier(s) référencé(s).\n")
    return hashes_seen, pdf_hashes_seen, phash_tree, tree_is_empty


# ─── Traitement principal ──────────────────────────────────────────────────────
def process_files(
    source_dir:      str,
    target_dir:      str,
    move_files:      bool,
    phash_threshold: int,
    cancel_event:    threading.Event,
    callbacks:       dict,
):
    on_progress = callbacks["on_progress"]
    on_log      = callbacks["on_log"]
    on_done     = callbacks["on_done"]

    # ── Validations ────────────────────────────────────────────────────────────
    if not os.path.isdir(source_dir):
        on_log("❌ Dossier source invalide ou introuvable.")
        on_done(None)
        return

    if os.path.abspath(source_dir) == os.path.abspath(target_dir):
        on_log("❌ La source et la destination ne peuvent pas être identiques.")
        on_done(None)
        return

    os.makedirs(target_dir, exist_ok=True)

    # ── Indexation de la destination existante ─────────────────────────────────
    hashes_seen, pdf_hashes_seen, phash_tree, tree_is_empty = index_existing_destination(
        target_dir, phash_threshold, cancel_event, on_log, on_progress
    )

    if cancel_event.is_set():
        on_log("⚠️  Annulé pendant l'indexation.")
        on_done(None)
        return

    # Remise à zéro de la barre avant le traitement principal
    on_progress(0, 1, "")

    # ── Scan de la source ──────────────────────────────────────────────────────
    all_files = []
    for root, _, files in os.walk(source_dir):
        for f in files:
            if f in SYSTEM_FILES or f.startswith("."):
                continue
            all_files.append(os.path.join(root, f))

    total = len(all_files)
    on_log(f"📂 {total} fichier(s) trouvé(s) dans la source — démarrage du traitement…\n")

    if total == 0:
        on_log("⚠️  Aucun fichier à traiter.")
        on_done({"ok": 0, "duplicate": 0, "error": 0})
        return

    doublon_dir = os.path.join(target_dir, "Doublon")
    stats = {"ok": 0, "duplicate": 0, "error": 0}

    # ── Boucle principale ──────────────────────────────────────────────────────
    for i, source_file in enumerate(all_files):

        if cancel_event.is_set():
            on_log("\n⚠️  Traitement annulé par l'utilisateur.")
            on_done(stats)
            return

        on_progress(i + 1, total, f"Traitement : {i + 1} / {total}")
        file_name = os.path.basename(source_file)
        ext       = os.path.splitext(file_name)[1].lower()

        # ── Doublon exact (SHA256) ─────────────────────────────────────────────
        file_hash    = get_file_hash(source_file)
        is_duplicate = bool(file_hash and file_hash in hashes_seen)

        # ── Doublon visuel pHash (images uniquement) ───────────────────────────
        visual_duplicate = False
        phash = None

        if not is_duplicate and ext in IMAGE_EXTENSIONS:
            phash = get_image_phash(source_file)
            if phash and not tree_is_empty:
                if phash_tree.find(phash, phash_threshold):
                    visual_duplicate = True

        # ── Doublon textuel PDF ────────────────────────────────────────────────
        pdf_duplicate = False
        pdf_text_hash = None

        if not is_duplicate and not visual_duplicate and ext == ".pdf":
            pdf_text_hash = get_pdf_text_hash(source_file)
            if pdf_text_hash and pdf_text_hash in pdf_hashes_seen:
                pdf_duplicate = True

        # ── Date de référence ──────────────────────────────────────────────────
        date     = get_exif_date(source_file) or get_file_date(source_file)
        date_str = date.strftime("%Y-%m-%d_%H-%M-%S") if date else "unknown_date"
        new_name = f"{date_str}_{file_name}"

        # ── Choix de la destination ────────────────────────────────────────────
        if is_duplicate or visual_duplicate or pdf_duplicate:
            os.makedirs(doublon_dir, exist_ok=True)
            target_base = doublon_dir

            if is_duplicate:
                dup_reason = "HASH"
            elif visual_duplicate:
                dup_reason = "VISUEL"
            else:
                dup_reason = "PDF"

            on_log(f"  [DOUBLON {dup_reason}] {file_name}")
            stats["duplicate"] += 1
        else:
            target_base = get_target_subfolder(source_file, target_dir)
            os.makedirs(target_base, exist_ok=True)

        # ── Résolution des conflits de noms ────────────────────────────────────
        target_file    = os.path.join(target_base, new_name)
        base, ext_orig = os.path.splitext(new_name)
        counter        = 1
        while os.path.exists(target_file):
            target_file = os.path.join(target_base, f"{base}_{counter}{ext_orig}")
            counter += 1

        # ── Copie / déplacement ────────────────────────────────────────────────
        try:
            if move_files:
                shutil.move(source_file, target_file)
            else:
                shutil.copy2(source_file, target_file)

            rel = os.path.relpath(target_file, target_dir)
            on_log(f"  [OK] {file_name}  →  {rel}")
            stats["ok"] += 1
        except Exception as e:
            on_log(f"  [ERREUR] {file_name} : {e}")
            stats["error"] += 1
            continue

        # ── Mise à jour des structures de déduplication ────────────────────────
        if file_hash:
            hashes_seen[file_hash] = target_file
        if phash:
            phash_tree.add(phash)
            tree_is_empty = False
        if pdf_text_hash:
            pdf_hashes_seen[pdf_text_hash] = target_file

    # ── Nettoyage des dossiers vides (mode déplacement uniquement) ─────────────
    if move_files:
        for root, _, _ in os.walk(source_dir, topdown=False):
            if not os.listdir(root):
                try:
                    os.rmdir(root)
                    on_log(f"  [SUPPRIMÉ] dossier vide : {os.path.basename(root)}")
                except Exception:
                    pass

    on_done(stats)


# ─── Interface graphique ───────────────────────────────────────────────────────
class ChronoSortApp:
    def __init__(self, root: tk.Tk):
        self.root         = root
        self.root.title("ChronoSort")
        self.root.resizable(False, False)
        self.cancel_event = threading.Event()
        self._build_ui()

    def _build_ui(self):
        # ── Dossiers ──────────────────────────────────────────────────────────
        frame_paths = ttk.LabelFrame(self.root, text=" Dossiers ", padding=8)
        frame_paths.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 4))

        ttk.Label(frame_paths, text="Source :").grid(row=0, column=0, sticky="w")
        self.source_var = tk.StringVar()
        ttk.Entry(frame_paths, textvariable=self.source_var, width=52).grid(row=0, column=1, padx=6)
        ttk.Button(frame_paths, text="Parcourir…", command=self._pick_source).grid(row=0, column=2)

        ttk.Label(frame_paths, text="Destination :").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.target_var = tk.StringVar()
        ttk.Entry(frame_paths, textvariable=self.target_var, width=52).grid(row=1, column=1, padx=6, pady=(6, 0))
        ttk.Button(frame_paths, text="Parcourir…", command=self._pick_target).grid(row=1, column=2, pady=(6, 0))

        # ── Note informationnelle ──────────────────────────────────────────────
        note = (
            "ℹ️  Vous pouvez réutiliser le même dossier de destination à chaque passe.\n"
            "   Les fichiers déjà présents seront indexés au démarrage : aucun doublon\n"
            "   ne sera introduit, même si le dossier source change."
        )
        ttk.Label(
            frame_paths, text=note,
            foreground="#888888", font=("TkDefaultFont", 8), justify="left"
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(8, 2))

        # ── Options ───────────────────────────────────────────────────────────
        frame_opts = ttk.LabelFrame(self.root, text=" Options ", padding=8)
        frame_opts.grid(row=1, column=0, sticky="ew", padx=10, pady=4)

        self.move_var = tk.BooleanVar()
        ttk.Checkbutton(
            frame_opts, text="Déplacer les fichiers (au lieu de copier)",
            variable=self.move_var
        ).grid(row=0, column=0, columnspan=3, sticky="w")

        ttk.Label(frame_opts, text="Seuil similarité visuelle (0 = strict · 10 = permissif) :").grid(
            row=1, column=0, sticky="w", pady=(6, 0)
        )
        self.threshold_var = tk.IntVar(value=DEFAULT_PHASH_THRESHOLD)
        ttk.Spinbox(
            frame_opts, from_=0, to=10, textvariable=self.threshold_var,
            width=5, state="readonly"
        ).grid(row=1, column=1, sticky="w", padx=8, pady=(6, 0))

        # ── Boutons ───────────────────────────────────────────────────────────
        frame_btns = ttk.Frame(self.root)
        frame_btns.grid(row=2, column=0, pady=6)

        self.start_btn = ttk.Button(frame_btns, text="▶  Lancer", command=self._start, width=14)
        self.start_btn.pack(side="left", padx=6)

        self.cancel_btn = ttk.Button(
            frame_btns, text="⏹  Annuler", command=self._cancel,
            state="disabled", width=14
        )
        self.cancel_btn.pack(side="left", padx=6)

        # ── Barre de progression ──────────────────────────────────────────────
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(
            self.root, variable=self.progress_var,
            maximum=100, length=560, mode="determinate"
        )
        self.progress_bar.grid(row=3, column=0, padx=10, pady=(0, 2))

        self.progress_label = ttk.Label(self.root, text="")
        self.progress_label.grid(row=4, column=0)

        # ── Zone de logs ──────────────────────────────────────────────────────
        frame_log = ttk.LabelFrame(self.root, text=" Journal ", padding=6)
        frame_log.grid(row=5, column=0, sticky="ew", padx=10, pady=(4, 10))

        self.log_area = scrolledtext.ScrolledText(
            frame_log, width=74, height=16,
            state="disabled", font=("Courier New", 9)
        )
        self.log_area.pack()

    def _pick_source(self):
        path = filedialog.askdirectory(title="Choisir le dossier source")
        if path:
            self.source_var.set(path)

    def _pick_target(self):
        path = filedialog.askdirectory(title="Choisir le dossier destination")
        if path:
            self.target_var.set(path)

    def _log(self, message: str):
        self.log_area.config(state="normal")
        self.log_area.insert("end", message + "\n")
        self.log_area.see("end")
        self.log_area.config(state="disabled")

    def _on_progress(self, current: int, total: int, label: str = ""):
        pct = (current / total) * 100 if total > 0 else 0
        self.progress_var.set(pct)
        self.progress_label.config(text=label)

    def _on_done(self, stats: dict | None):
        self.start_btn.config(state="normal")
        self.cancel_btn.config(state="disabled")
        if stats is not None:
            self._log(
                f"\n{'─'*60}\n"
                f"  ✅ Traités   : {stats['ok']}\n"
                f"  📋 Doublons  : {stats['duplicate']}\n"
                f"  ❌ Erreurs   : {stats['error']}\n"
                f"{'─'*60}"
            )
            self.progress_label.config(text="Terminé !")

    def _start(self):
        source = self.source_var.get().strip()
        target = self.target_var.get().strip()

        if not source or not target:
            self._log("❌ Veuillez sélectionner les dossiers source et destination.")
            return

        self.cancel_event.clear()
        self.start_btn.config(state="disabled")
        self.cancel_btn.config(state="normal")
        self.progress_var.set(0)
        self.progress_label.config(text="")
        self.log_area.config(state="normal")
        self.log_area.delete("1.0", "end")
        self.log_area.config(state="disabled")

        callbacks = {
            "on_progress": lambda c, t, l="": self.root.after(0, self._on_progress, c, t, l),
            "on_log":      lambda msg:  self.root.after(0, self._log, msg),
            "on_done":     lambda s:    self.root.after(0, self._on_done, s),
        }

        thread = threading.Thread(
            target=process_files,
            args=(
                source, target,
                self.move_var.get(),
                self.threshold_var.get(),
                self.cancel_event,
                callbacks,
            ),
            daemon=True,
        )
        thread.start()

    def _cancel(self):
        self.cancel_event.set()
        self.cancel_btn.config(state="disabled")
        self._log("⏹  Annulation en cours…")


# ─── Point d'entrée ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    root = tk.Tk()
    ChronoSortApp(root)
    root.mainloop()
