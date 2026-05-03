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
DEFAULT_PHASH_THRESHOLD = 5
MODE_TRI                = "tri"
MODE_MIROIR             = "miroir"

ACCENT      = "#5b5ef4"
ACCENT_DARK = "#4340c4"
CLR_MUTED   = "#6b7280"
CLR_CARD_ON = "#eff6ff"
CLR_BORDER  = "#d1d5db"

SYSTEM_FILES = {
    ".DS_Store", "Thumbs.db", "desktop.ini",
    ".localized", ".Spotlight-V100", "ehthumbs.db",
}

# ─── Catégories ───────────────────────────────────────────────────────────────
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
    # Documents
    ".pdf":  ("PDF",        False),
    ".doc":  ("Word",       False), ".docx": ("Word",       False),
    ".odt":  ("Word",       False), ".rtf":  ("Word",       False),
    ".xls":  ("Excel",      False), ".xlsx": ("Excel",      False),
    ".ods":  ("Excel",      False), ".csv":  ("Excel",      False),
    ".ppt":  ("PowerPoint", False), ".pptx": ("PowerPoint", False),
    ".odp":  ("PowerPoint", False),
    # Audio
    ".mp3":  ("Audio", True), ".wav":  ("Audio", True),
    ".flac": ("Audio", True), ".aac":  ("Audio", True),
    ".ogg":  ("Audio", True), ".wma":  ("Audio", True),
    ".m4a":  ("Audio", True), ".opus": ("Audio", True),
    # Archives
    ".zip": ("Archives", False), ".rar": ("Archives", False),
    ".7z":  ("Archives", False), ".tar": ("Archives", False),
    ".gz":  ("Archives", False), ".bz2": ("Archives", False),
}

IMAGE_EXTENSIONS = {k for k, (c, _) in EXTENSION_CATEGORIES.items() if c == "Images"}


def get_category_subfolder(file_path: str, base_dir: str) -> str:
    """Retourne le dossier catégorisé pour un fichier, à partir d'un dossier de base."""
    ext = os.path.splitext(file_path)[1].lower()
    if ext in EXTENSION_CATEGORIES:
        category, use_ext_sub = EXTENSION_CATEGORIES[ext]
        if use_ext_sub:
            return os.path.join(base_dir, category, ext.lstrip(".").upper())
        return os.path.join(base_dir, category)
    return os.path.join(base_dir, "Autres")


# ─── Hashing ──────────────────────────────────────────────────────────────────
def get_file_hash(path: str) -> str | None:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while chunk := f.read(CHUNK_SIZE):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def get_image_phash(path: str):
    try:
        with Image.open(path) as img:
            return imagehash.phash(img)
    except Exception:
        return None


def get_pdf_text_hash(path: str) -> str | None:
    """Hash du contenu texte d'un PDF. Retourne None si PDF scanné (pas de texte)."""
    try:
        reader = PdfReader(path)
        text = "".join(page.extract_text() or "" for page in reader.pages)
        if not text.strip():
            return None
        return hashlib.sha256(text.encode("utf-8")).hexdigest()
    except Exception:
        return None


def get_exif_date(path: str) -> datetime | None:
    try:
        with Image.open(path) as img:
            exif = img.getexif()
            if exif:
                for tag, value in exif.items():
                    if TAGS.get(tag, tag) in ("DateTimeOriginal", "DateTime"):
                        return datetime.strptime(value, "%Y:%m:%d %H:%M:%S")
    except Exception:
        pass
    return None


def get_file_date(path: str) -> datetime | None:
    try:
        return datetime.fromtimestamp(os.path.getmtime(path))
    except Exception:
        return None


# ─── État de déduplication ────────────────────────────────────────────────────
class DedupState:
    """Encapsule les trois structures de déduplication : SHA256, pHash, hash texte PDF."""

    def __init__(self):
        self.hashes:      dict            = {}
        self.pdf_hashes:  dict            = {}
        self.phash_tree:  pybktree.BKTree = pybktree.BKTree(lambda a, b: abs(a - b))
        self._phash_empty: bool           = True

    def add(self, file_hash=None, phash=None, pdf_hash=None, path: str = ""):
        if file_hash:
            self.hashes[file_hash] = path
        if phash is not None:
            self.phash_tree.add(phash)
            self._phash_empty = False
        if pdf_hash:
            self.pdf_hashes[pdf_hash] = path

    def is_exact_duplicate(self, file_hash: str | None) -> bool:
        return bool(file_hash and file_hash in self.hashes)

    def is_visual_duplicate(self, phash, threshold: int) -> bool:
        if phash is None or self._phash_empty:
            return False
        return bool(self.phash_tree.find(phash, threshold))

    def is_pdf_duplicate(self, pdf_hash: str | None) -> bool:
        return bool(pdf_hash and pdf_hash in self.pdf_hashes)


# ─── Utilitaires de transfert ─────────────────────────────────────────────────
def resolve_conflict(folder: str, filename: str) -> str:
    """Retourne un chemin sans conflit en suffixant un compteur si nécessaire."""
    dst = os.path.join(folder, filename)
    if not os.path.exists(dst):
        return dst
    base, ext = os.path.splitext(filename)
    i = 1
    while os.path.exists(dst):
        dst = os.path.join(folder, f"{base}_{i}{ext}")
        i += 1
    return dst


def transfer(src: str, dst: str, move: bool):
    if move:
        shutil.move(src, dst)
    else:
        shutil.copy2(src, dst)


def cleanup_empty_dirs(directory: str, on_log):
    for root, _, _ in os.walk(directory, topdown=False):
        if not os.listdir(root):
            try:
                os.rmdir(root)
                on_log(f"  [SUPPRIMÉ] dossier vide : {os.path.basename(root)}")
            except Exception:
                pass


def scan_dir(directory: str) -> list[str]:
    return [
        os.path.join(root, f)
        for root, _, files in os.walk(directory)
        for f in files
        if f not in SYSTEM_FILES
    ]


# ─── Indexation destination ───────────────────────────────────────────────────
def index_destination(
    target_dir:   str,
    mode:         str,
    threshold:    int,
    cancel_event: threading.Event,
    on_log,
    on_progress,
) -> DedupState:
    """
    Pré-remplit l'état de déduplication avec les fichiers déjà présents
    dans la destination. Garantit la cohérence entre plusieurs passes.
    """
    state = DedupState()

    if not os.path.isdir(target_dir):
        return state

    existing = scan_dir(target_dir)
    count    = len(existing)

    if count == 0:
        on_log("📂 Destination vierge — aucun fichier existant à indexer.\n")
        return state

    on_log(f"🔍 Indexation de la destination : {count} fichier(s) déjà présent(s)…")
    on_log("   (Les doublons seront détectés même si le dossier source change.)\n")

    for i, path in enumerate(existing):
        if cancel_event.is_set():
            break

        ext       = os.path.splitext(path)[1].lower()
        file_hash = get_file_hash(path)
        phash     = get_image_phash(path) if (mode == MODE_TRI and ext in IMAGE_EXTENSIONS) else None
        pdf_hash  = get_pdf_text_hash(path) if (mode == MODE_TRI and ext == ".pdf") else None

        state.add(file_hash=file_hash, phash=phash, pdf_hash=pdf_hash, path=path)
        on_progress(i + 1, count, f"Indexation : {i + 1} / {count}")

    on_log(f"✅ Indexation terminée — {count} fichier(s) référencé(s).\n")
    return state


# ─── Mode Tri ─────────────────────────────────────────────────────────────────
def run_mode_tri(
    source_dir:         str,
    target_dir:         str,
    move_files:         bool,
    threshold:          int,
    delete_exact_dupes: bool,
    state:              DedupState,
    all_files:          list[str],
    cancel_event:       threading.Event,
    on_log,
    on_progress,
) -> dict:
    stats       = {"ok": 0, "deleted": 0, "duplicate": 0, "error": 0}
    doublon_dir = os.path.join(target_dir, "Doublon")
    total       = len(all_files)

    for i, src in enumerate(all_files):
        if cancel_event.is_set():
            on_log("\n⚠️  Traitement annulé par l'utilisateur.")
            return stats

        on_progress(i + 1, total, f"Traitement : {i + 1} / {total}")
        filename = os.path.basename(src)
        ext      = os.path.splitext(filename)[1].lower()

        # ── Détection ─────────────────────────────────────────────────────────
        file_hash = get_file_hash(src)
        is_exact  = state.is_exact_duplicate(file_hash)

        phash      = None
        is_visual  = False
        if not is_exact and ext in IMAGE_EXTENSIONS:
            phash     = get_image_phash(src)
            is_visual = state.is_visual_duplicate(phash, threshold)

        pdf_hash = None
        is_pdf   = False
        if not is_exact and not is_visual and ext == ".pdf":
            pdf_hash = get_pdf_text_hash(src)
            is_pdf   = state.is_pdf_duplicate(pdf_hash)

        # ── Renommage par date ─────────────────────────────────────────────────
        date     = get_exif_date(src) or get_file_date(src)
        date_str = date.strftime("%Y-%m-%d_%H-%M-%S") if date else "unknown_date"
        new_name = f"{date_str}_{filename}"

        # ── Routage ───────────────────────────────────────────────────────────
        if is_exact and delete_exact_dupes:
            try:
                os.remove(src)
                on_log(f"  [SUPPRIMÉ]     {filename}")
                stats["deleted"] += 1
            except Exception as e:
                on_log(f"  [ERREUR] {filename} : {e}")
                stats["error"] += 1
            continue

        is_dup = is_exact or is_visual or is_pdf
        if is_dup:
            reason      = "HASH" if is_exact else ("VISUEL" if is_visual else "PDF")
            target_base = get_category_subfolder(src, doublon_dir)
            on_log(f"  [DOUBLON {reason:<6}] {filename}")
            stats["duplicate"] += 1
        else:
            target_base = get_category_subfolder(src, target_dir)

        os.makedirs(target_base, exist_ok=True)
        dst = resolve_conflict(target_base, new_name)

        try:
            transfer(src, dst, move_files)
            if not is_dup:
                on_log(f"  [OK] {filename}  →  {os.path.relpath(dst, target_dir)}")
                stats["ok"] += 1
        except Exception as e:
            on_log(f"  [ERREUR] {filename} : {e}")
            stats["error"] += 1
            continue

        # Mise à jour état
        if not is_exact:
            state.add(file_hash=file_hash, phash=phash if not is_visual else None,
                      pdf_hash=pdf_hash if not is_pdf else None, path=dst)

    return stats


# ─── Mode Miroir ──────────────────────────────────────────────────────────────
def run_mode_miroir(
    source_dir:   str,
    target_dir:   str,
    move_files:   bool,
    state:        DedupState,
    all_files:    list[str],
    cancel_event: threading.Event,
    on_log,
    on_progress,
) -> dict:
    """
    Reproduit l'arborescence source dans la destination.
    Supprime les doublons exacts (SHA256) sans les déplacer.
    Pas de renommage, pas de tri par catégorie.
    """
    stats = {"ok": 0, "deleted": 0, "duplicate": 0, "error": 0}
    total = len(all_files)

    for i, src in enumerate(all_files):
        if cancel_event.is_set():
            on_log("\n⚠️  Traitement annulé par l'utilisateur.")
            return stats

        on_progress(i + 1, total, f"Traitement : {i + 1} / {total}")
        filename = os.path.basename(src)

        file_hash = get_file_hash(src)

        if state.is_exact_duplicate(file_hash):
            try:
                os.remove(src)
                on_log(f"  [SUPPRIMÉ]  {filename}  (doublon exact SHA256)")
                stats["deleted"] += 1
            except Exception as e:
                on_log(f"  [ERREUR] {filename} : {e}")
                stats["error"] += 1
            continue

        # Reproduction de l'arborescence relative
        rel_path    = os.path.relpath(src, source_dir)
        target_base = os.path.join(target_dir, os.path.dirname(rel_path))
        os.makedirs(target_base, exist_ok=True)
        dst = resolve_conflict(target_base, filename)

        try:
            transfer(src, dst, move_files)
            on_log(f"  [OK] {rel_path}  →  {os.path.relpath(dst, target_dir)}")
            stats["ok"] += 1
        except Exception as e:
            on_log(f"  [ERREUR] {filename} : {e}")
            stats["error"] += 1
            continue

        if file_hash:
            state.add(file_hash=file_hash, path=dst)

    return stats


# ─── Orchestrateur ────────────────────────────────────────────────────────────
def process_files(
    source_dir:         str,
    target_dir:         str,
    mode:               str,
    move_files:         bool,
    threshold:          int,
    delete_exact_dupes: bool,
    cancel_event:       threading.Event,
    callbacks:          dict,
):
    on_progress = callbacks["on_progress"]
    on_log      = callbacks["on_log"]
    on_done     = callbacks["on_done"]

    if not os.path.isdir(source_dir):
        on_log("❌ Dossier source invalide ou introuvable.")
        on_done(None)
        return

    if os.path.abspath(source_dir) == os.path.abspath(target_dir):
        on_log("❌ La source et la destination ne peuvent pas être identiques.")
        on_done(None)
        return

    os.makedirs(target_dir, exist_ok=True)

    state = index_destination(target_dir, mode, threshold, cancel_event, on_log, on_progress)
    if cancel_event.is_set():
        on_log("⚠️  Annulé pendant l'indexation.")
        on_done(None)
        return

    on_progress(0, 1, "")

    all_files = scan_dir(source_dir)
    total     = len(all_files)
    mode_label = "Mode Tri" if mode == MODE_TRI else "Mode Miroir"
    on_log(f"📂 {total} fichier(s) trouvé(s) — {mode_label} — démarrage…\n")

    if total == 0:
        on_log("⚠️  Aucun fichier à traiter.")
        on_done({"ok": 0, "deleted": 0, "duplicate": 0, "error": 0})
        return

    if mode == MODE_TRI:
        stats = run_mode_tri(
            source_dir, target_dir, move_files, threshold,
            delete_exact_dupes, state, all_files, cancel_event, on_log, on_progress,
        )
    else:
        stats = run_mode_miroir(
            source_dir, target_dir, move_files,
            state, all_files, cancel_event, on_log, on_progress,
        )

    if move_files:
        cleanup_empty_dirs(source_dir, on_log)

    on_done(stats)


# ─── Interface graphique ───────────────────────────────────────────────────────
class ChronoSortApp:
    def __init__(self, root: tk.Tk):
        self.root         = root
        self.cancel_event = threading.Event()
        self._setup_window()
        self._setup_styles()
        self._build_ui()

    # ── Fenêtre ───────────────────────────────────────────────────────────────
    def _setup_window(self):
        self.root.title("ChronoSort")
        self.root.minsize(680, 620)
        self.root.resizable(True, True)
        # Centrage
        self.root.update_idletasks()
        w, h = 760, 760
        x = (self.root.winfo_screenwidth()  - w) // 2
        y = (self.root.winfo_screenheight() - h) // 2
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        # Grille racine : colonne extensible, rangée du journal extensible
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(5, weight=1)  # rangée journal

    # ── Styles ttk ────────────────────────────────────────────────────────────
    def _setup_styles(self):
        s = ttk.Style()
        s.theme_use("clam")
        s.configure("TFrame",       background="#f9fafb")
        s.configure("TLabel",       background="#f9fafb", foreground="#111827")
        s.configure("TLabelframe",  background="#f9fafb", foreground="#374151",
                    bordercolor=CLR_BORDER, relief="solid", borderwidth=1)
        s.configure("TLabelframe.Label", background="#f9fafb", foreground="#374151",
                    font=("Segoe UI", 9, "bold"))
        s.configure("TCheckbutton", background="#f9fafb", foreground="#111827")
        s.configure("TSpinbox",     fieldbackground="white", foreground="#111827")
        s.configure("Accent.TButton",
                    background=ACCENT, foreground="white",
                    font=("Segoe UI", 9, "bold"), borderwidth=0, relief="flat")
        s.map("Accent.TButton",
              background=[("active", ACCENT_DARK), ("disabled", "#a5b4fc")])
        s.configure("Cancel.TButton",
                    background="#e5e7eb", foreground="#374151",
                    font=("Segoe UI", 9), borderwidth=0, relief="flat")
        s.map("Cancel.TButton",
              background=[("active", "#d1d5db"), ("disabled", "#f3f4f6")])
        s.configure("Horizontal.TProgressbar",
                    troughcolor="#e5e7eb", background=ACCENT,
                    borderwidth=0, thickness=8)
        self.root.configure(bg="#f9fafb")

    # ── Construction UI ───────────────────────────────────────────────────────
    def _build_ui(self):
        self._build_header()         # row 0
        self._build_paths_frame()    # row 1
        self._build_mode_frame()     # row 2
        self._build_options_frame()  # row 3
        self._build_controls()       # row 4
        self._build_log_frame()      # row 5

    # ── En-tête ───────────────────────────────────────────────────────────────
    def _build_header(self):
        header = tk.Frame(self.root, bg=ACCENT)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)

        tk.Label(
            header, text="📸  ChronoSort",
            bg=ACCENT, fg="white", font=("Segoe UI", 14, "bold"), anchor="w"
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(10, 2))
        tk.Label(
            header, text="Tri  ·  Déduplication  ·  Organisation automatique",
            bg=ACCENT, fg="#c7d2fe", font=("Segoe UI", 8), anchor="w"
        ).grid(row=1, column=0, sticky="w", padx=18, pady=(0, 10))

    # ── Dossiers ──────────────────────────────────────────────────────────────
    def _build_paths_frame(self):
        frame = ttk.LabelFrame(self.root, text="  Dossiers", padding=(12, 8))
        frame.grid(row=1, column=0, sticky="ew", padx=12, pady=(10, 4))
        frame.columnconfigure(1, weight=1)

        self.source_var = tk.StringVar()
        self.target_var = tk.StringVar()

        for row, label, var, cmd in [
            (0, "Source :",      self.source_var, self._pick_source),
            (1, "Destination :", self.target_var, self._pick_target),
        ]:
            ttk.Label(frame, text=label, font=("Segoe UI", 9)).grid(
                row=row, column=0, sticky="w", pady=(0 if row == 0 else 6, 0))
            ttk.Entry(frame, textvariable=var, font=("Segoe UI", 9)).grid(
                row=row, column=1, sticky="ew", padx=8, pady=(0 if row == 0 else 6, 0))
            ttk.Button(frame, text="Parcourir…", command=cmd).grid(
                row=row, column=2, pady=(0 if row == 0 else 6, 0))

        ttk.Label(
            frame,
            text="ℹ️  Le même dossier de destination peut être réutilisé d'une passe à l'autre —"
                 " les fichiers existants sont indexés au démarrage.",
            foreground=CLR_MUTED, font=("Segoe UI", 8), wraplength=580, justify="left",
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(10, 2))

    # ── Sélection du mode ─────────────────────────────────────────────────────
    def _build_mode_frame(self):
        frame = ttk.LabelFrame(self.root, text="  Mode de fonctionnement", padding=(12, 8))
        frame.grid(row=2, column=0, sticky="ew", padx=12, pady=4)
        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)

        self.mode_var = tk.StringVar(value=MODE_TRI)

        # ── Carte Mode Tri ─────────────────────────────────────────────────────
        self.card_tri = tk.Frame(frame, bg=CLR_CARD_ON, bd=2,
                                 relief="solid", cursor="hand2")
        self.card_tri.grid(row=0, column=0, sticky="nsew", padx=(0, 6), pady=2)
        self.card_tri.bind("<Button-1>", lambda e: self._set_mode(MODE_TRI))

        tk.Radiobutton(
            self.card_tri, text="✦  Mode Tri", variable=self.mode_var, value=MODE_TRI,
            font=("Segoe UI", 10, "bold"), bg=CLR_CARD_ON, activebackground=CLR_CARD_ON,
            fg=ACCENT, command=lambda: self._set_mode(MODE_TRI), cursor="hand2",
        ).pack(anchor="w", padx=10, pady=(10, 2))
        tk.Label(
            self.card_tri,
            text="Renomme les fichiers par date (EXIF ou\n"
                 "modification) et les classe par catégorie.\n"
                 "Détecte les doublons via SHA256, pHash\n"
                 "et contenu PDF.",
            bg=CLR_CARD_ON, fg="#374151", font=("Segoe UI", 8), justify="left",
        ).pack(anchor="w", padx=20, pady=(0, 12))

        # ── Carte Mode Miroir ──────────────────────────────────────────────────
        self.card_miroir = tk.Frame(frame, bg="white", bd=1,
                                    relief="solid", cursor="hand2")
        self.card_miroir.grid(row=0, column=1, sticky="nsew", padx=(6, 0), pady=2)
        self.card_miroir.bind("<Button-1>", lambda e: self._set_mode(MODE_MIROIR))

        tk.Radiobutton(
            self.card_miroir, text="⟺  Mode Miroir", variable=self.mode_var, value=MODE_MIROIR,
            font=("Segoe UI", 10, "bold"), bg="white", activebackground=CLR_CARD_ON,
            fg=CLR_MUTED, command=lambda: self._set_mode(MODE_MIROIR), cursor="hand2",
        ).pack(anchor="w", padx=10, pady=(10, 2))
        tk.Label(
            self.card_miroir,
            text="Reproduit l'arborescence source à\n"
                 "l'identique. Aucun renommage ni tri par\n"
                 "catégorie. Supprime uniquement les\n"
                 "doublons exacts (SHA256).",
            bg="white", fg="#374151", font=("Segoe UI", 8), justify="left",
        ).pack(anchor="w", padx=20, pady=(0, 12))

    def _set_mode(self, mode: str):
        self.mode_var.set(mode)
        # Mise à jour visuelle des cartes
        if mode == MODE_TRI:
            self._style_card(self.card_tri,    selected=True)
            self._style_card(self.card_miroir, selected=False)
            self.frame_tri_opts.grid()
        else:
            self._style_card(self.card_tri,    selected=False)
            self._style_card(self.card_miroir, selected=True)
            self.frame_tri_opts.grid_remove()

    def _style_card(self, card: tk.Frame, selected: bool):
        bg     = CLR_CARD_ON if selected else "white"
        bd     = 2           if selected else 1
        relief = "solid"
        card.config(bg=bg, bd=bd, relief=relief)
        for child in card.winfo_children():
            try:
                child.config(bg=bg)
            except Exception:
                pass

    # ── Options ───────────────────────────────────────────────────────────────
    def _build_options_frame(self):
        frame = ttk.LabelFrame(self.root, text="  Options", padding=(12, 8))
        frame.grid(row=3, column=0, sticky="ew", padx=12, pady=4)
        frame.columnconfigure(0, weight=1)

        self.move_var = tk.BooleanVar()
        ttk.Checkbutton(
            frame, text="Déplacer les fichiers (au lieu de copier)",
            variable=self.move_var,
        ).grid(row=0, column=0, columnspan=3, sticky="w")

        # ── Options spécifiques Mode Tri ───────────────────────────────────────
        self.frame_tri_opts = ttk.Frame(frame)
        self.frame_tri_opts.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(4, 0))
        self.frame_tri_opts.columnconfigure(0, weight=1)

        sep = ttk.Separator(self.frame_tri_opts, orient="horizontal")
        sep.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(6, 8))

        self.delete_exact_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            self.frame_tri_opts,
            text="Supprimer les doublons exacts (SHA256) — sans confirmation",
            variable=self.delete_exact_var,
            command=self._on_delete_toggle,
        ).grid(row=1, column=0, columnspan=3, sticky="w")

        self.delete_warn = ttk.Label(
            self.frame_tri_opts,
            text="   ⚠️  Les doublons visuels (pHash) et PDF restent déplacés vers Doublon/ pour vérification.",
            foreground="#b45309", font=("Segoe UI", 8), wraplength=580, justify="left",
        )
        self.delete_warn.grid(row=2, column=0, columnspan=3, sticky="w", pady=(2, 0))
        self.delete_warn.grid_remove()

        ttk.Label(
            self.frame_tri_opts, text="Seuil similarité visuelle :",
            font=("Segoe UI", 9),
        ).grid(row=3, column=0, sticky="w", pady=(8, 0))

        self.threshold_var = tk.IntVar(value=DEFAULT_PHASH_THRESHOLD)
        ttk.Spinbox(
            self.frame_tri_opts, from_=0, to=10,
            textvariable=self.threshold_var, width=5, state="readonly",
        ).grid(row=3, column=1, sticky="w", padx=8, pady=(8, 0))

        ttk.Label(
            self.frame_tri_opts, text="0 = identique strict   ·   10 = très permissif",
            foreground=CLR_MUTED, font=("Segoe UI", 8),
        ).grid(row=3, column=2, sticky="w", pady=(8, 0))

    def _on_delete_toggle(self):
        if self.delete_exact_var.get():
            self.delete_warn.grid()
        else:
            self.delete_warn.grid_remove()

    # ── Boutons + barre de progression ────────────────────────────────────────
    def _build_controls(self):
        frame = ttk.Frame(self.root)
        frame.grid(row=4, column=0, sticky="ew", padx=12, pady=(6, 2))
        frame.columnconfigure(2, weight=1)

        self.start_btn = ttk.Button(
            frame, text="▶  Lancer", style="Accent.TButton",
            command=self._start, width=14,
        )
        self.start_btn.grid(row=0, column=0, padx=(0, 6), pady=(0, 8))

        self.cancel_btn = ttk.Button(
            frame, text="⏹  Annuler", style="Cancel.TButton",
            command=self._cancel, state="disabled", width=14,
        )
        self.cancel_btn.grid(row=0, column=1, padx=(0, 12), pady=(0, 8))

        self.progress_label = ttk.Label(
            frame, text="", foreground=CLR_MUTED, font=("Segoe UI", 8),
        )
        self.progress_label.grid(row=0, column=2, sticky="w", pady=(0, 8))

        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(
            frame, variable=self.progress_var,
            maximum=100, mode="determinate", style="Horizontal.TProgressbar",
        )
        self.progress_bar.grid(row=1, column=0, columnspan=3, sticky="ew")

    # ── Journal ───────────────────────────────────────────────────────────────
    def _build_log_frame(self):
        frame = ttk.LabelFrame(self.root, text="  Journal", padding=(8, 6))
        frame.grid(row=5, column=0, sticky="nsew", padx=12, pady=(0, 10))
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        self.log_area = scrolledtext.ScrolledText(
            frame, state="disabled", font=("Consolas", 8),
            bg="#111827", fg="#d1fae5", insertbackground="white",
            relief="flat", bd=0, wrap="none",
        )
        self.log_area.grid(row=0, column=0, sticky="nsew")

    # ── Sélecteurs de dossier ─────────────────────────────────────────────────
    def _pick_source(self):
        if path := filedialog.askdirectory(title="Choisir le dossier source"):
            self.source_var.set(path)

    def _pick_target(self):
        if path := filedialog.askdirectory(title="Choisir le dossier destination"):
            self.target_var.set(path)

    # ── Callbacks thread-safe ─────────────────────────────────────────────────
    def _log(self, message: str):
        self.log_area.config(state="normal")
        self.log_area.insert("end", message + "\n")
        self.log_area.see("end")
        self.log_area.config(state="disabled")

    def _on_progress(self, current: int, total: int, label: str = ""):
        self.progress_var.set((current / total * 100) if total > 0 else 0)
        self.progress_label.config(text=label)

    def _on_done(self, stats: dict | None):
        self.start_btn.config(state="normal")
        self.cancel_btn.config(state="disabled")
        if stats is not None:
            sep = "─" * 52
            self._log(
                f"\n{sep}\n"
                f"  ✅  Traités    : {stats['ok']}\n"
                f"  🗑️   Supprimés  : {stats['deleted']}\n"
                f"  📋  Doublons   : {stats['duplicate']}\n"
                f"  ❌  Erreurs    : {stats['error']}\n"
                f"{sep}"
            )
        self.progress_label.config(text="Terminé !" if stats is not None else "Annulé.")

    # ── Lancement ─────────────────────────────────────────────────────────────
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
            "on_log":      lambda msg:         self.root.after(0, self._log, msg),
            "on_done":     lambda s:           self.root.after(0, self._on_done, s),
        }

        threading.Thread(
            target=process_files,
            args=(
                source, target,
                self.mode_var.get(),
                self.move_var.get(),
                self.threshold_var.get(),
                self.delete_exact_var.get(),
                self.cancel_event,
                callbacks,
            ),
            daemon=True,
        ).start()

    def _cancel(self):
        self.cancel_event.set()
        self.cancel_btn.config(state="disabled")
        self._log("⏹  Annulation en cours…")


# ─── Point d'entrée ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    root = tk.Tk()
    ChronoSortApp(root)
    root.mainloop()
