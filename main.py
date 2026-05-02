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

# ─── Constantes ───────────────────────────────────────────────────────────────
CHUNK_SIZE = 8192
DEFAULT_PHASH_THRESHOLD = 5  # 0 = identique strict, 10 = très permissif

SYSTEM_FILES = {
    ".DS_Store", "Thumbs.db", "desktop.ini",
    ".localized", ".Spotlight-V100", "ehthumbs.db",
}


# ─── Hash fichier (SHA256) ─────────────────────────────────────────────────────
def get_file_hash(path):
    try:
        hasher = hashlib.sha256()
        with open(path, "rb") as f:
            while chunk := f.read(CHUNK_SIZE):
                hasher.update(chunk)
        return hasher.hexdigest()
    except Exception:
        return None


# ─── Hash visuel (images uniquement) ──────────────────────────────────────────
def get_image_phash(path):
    try:
        with Image.open(path) as img:
            return imagehash.phash(img)
    except Exception:
        return None


# ─── EXIF ──────────────────────────────────────────────────────────────────────
def get_exif_date(path):
    try:
        with Image.open(path) as image:
            exif = image.getexif()  # API publique (Pillow >= 6.0)
            if exif:
                for tag, value in exif.items():
                    tag_name = TAGS.get(tag, tag)
                    if tag_name in ("DateTimeOriginal", "DateTime"):
                        return datetime.strptime(value, "%Y:%m:%d %H:%M:%S")
    except Exception:
        pass
    return None


# ─── Fallback date ─────────────────────────────────────────────────────────────
def get_file_date(path):
    try:
        return datetime.fromtimestamp(os.path.getmtime(path))
    except Exception:
        return None


# ─── Traitement principal ──────────────────────────────────────────────────────
def process_files(source_dir, target_dir, move_files, phash_threshold, cancel_event, callbacks):
    """
    Paramètres
    ----------
    source_dir       : dossier source
    target_dir       : dossier destination
    move_files       : True = déplacer, False = copier
    phash_threshold  : seuil de tolérance pour la similarité visuelle
    cancel_event     : threading.Event — déclenché = annulation demandée
    callbacks        : dict {on_progress, on_log, on_done}
    """
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

    # ── Scan initial ───────────────────────────────────────────────────────────
    all_files = []
    for root, _, files in os.walk(source_dir):
        for f in files:
            if f in SYSTEM_FILES or f.startswith("."):
                continue
            all_files.append(os.path.join(root, f))

    total = len(all_files)
    on_log(f"📂 {total} fichier(s) trouvé(s) — démarrage du traitement…\n")

    if total == 0:
        on_log("⚠️  Aucun fichier à traiter.")
        on_done({"ok": 0, "duplicate": 0, "error": 0})
        return

    # ── Structures de déduplication ────────────────────────────────────────────
    hashes_seen  = {}
    phash_tree   = pybktree.BKTree(lambda a, b: abs(a - b))
    tree_is_empty = True

    doublon_dir = os.path.join(target_dir, "Doublon")
    stats = {"ok": 0, "duplicate": 0, "error": 0}

    # ── Boucle principale ──────────────────────────────────────────────────────
    for i, source_file in enumerate(all_files):

        if cancel_event.is_set():
            on_log("\n⚠️  Traitement annulé par l'utilisateur.")
            on_done(stats)
            return

        on_progress(i + 1, total)
        file_name = os.path.basename(source_file)

        # Doublon exact (hash SHA256)
        file_hash    = get_file_hash(source_file)
        is_duplicate = bool(file_hash and file_hash in hashes_seen)

        # Doublon visuel (pHash, images uniquement)
        visual_duplicate = False
        phash = get_image_phash(source_file)

        if phash and not tree_is_empty:
            if phash_tree.find(phash, phash_threshold):
                visual_duplicate = True

        # Date de référence
        date     = get_exif_date(source_file) or get_file_date(source_file)
        date_str = date.strftime("%Y-%m-%d_%H-%M-%S") if date else "unknown_date"
        new_name = f"{date_str}_{file_name}"

        # Choix de la destination
        if is_duplicate or visual_duplicate:
            os.makedirs(doublon_dir, exist_ok=True)
            target_base = doublon_dir
            reason      = "HASH" if is_duplicate else "VISUEL"
            on_log(f"  [DOUBLON {reason}] {file_name}")
            stats["duplicate"] += 1
        else:
            target_base = target_dir

        # Résolution des conflits de noms
        target_file = os.path.join(target_base, new_name)
        base, ext   = os.path.splitext(new_name)
        counter     = 1
        while os.path.exists(target_file):
            target_file = os.path.join(target_base, f"{base}_{counter}{ext}")
            counter += 1

        # Copie / déplacement
        try:
            if move_files:
                shutil.move(source_file, target_file)
            else:
                shutil.copy2(source_file, target_file)
            on_log(f"  [OK] {file_name}  →  {os.path.relpath(target_file, target_dir)}")
            stats["ok"] += 1
        except Exception as e:
            on_log(f"  [ERREUR] {file_name} : {e}")
            stats["error"] += 1
            continue

        # Mise à jour des structures de déduplication
        if file_hash:
            hashes_seen[file_hash] = target_file

        if phash:
            phash_tree.add(phash)
            tree_is_empty = False

    # ── Nettoyage des dossiers vides (déplacement uniquement) ──────────────────
    if move_files:
        for root, _, files in os.walk(source_dir, topdown=False):
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

    # ── Construction de l'interface ────────────────────────────────────────────
    def _build_ui(self):
        PAD = {"padx": 10, "pady": 4}

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

    # ── Sélecteurs de dossiers ─────────────────────────────────────────────────
    def _pick_source(self):
        path = filedialog.askdirectory(title="Choisir le dossier source")
        if path:
            self.source_var.set(path)

    def _pick_target(self):
        path = filedialog.askdirectory(title="Choisir le dossier destination")
        if path:
            self.target_var.set(path)

    # ── Mise à jour du journal (thread-safe via root.after) ───────────────────
    def _log(self, message: str):
        self.log_area.config(state="normal")
        self.log_area.insert("end", message + "\n")
        self.log_area.see("end")
        self.log_area.config(state="disabled")

    # ── Mise à jour de la barre de progression ─────────────────────────────────
    def _on_progress(self, current: int, total: int):
        pct = (current / total) * 100 if total > 0 else 0
        self.progress_var.set(pct)
        self.progress_label.config(text=f"{current} / {total} fichiers")

    # ── Fin du traitement ──────────────────────────────────────────────────────
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

    # ── Lancement ─────────────────────────────────────────────────────────────
    def _start(self):
        source = self.source_var.get().strip()
        target = self.target_var.get().strip()

        if not source or not target:
            self._log("❌ Veuillez sélectionner les dossiers source et destination.")
            return

        # Réinitialisation
        self.cancel_event.clear()
        self.start_btn.config(state="disabled")
        self.cancel_btn.config(state="normal")
        self.progress_var.set(0)
        self.progress_label.config(text="")
        self.log_area.config(state="normal")
        self.log_area.delete("1.0", "end")
        self.log_area.config(state="disabled")

        callbacks = {
            "on_progress": lambda c, t: self.root.after(0, self._on_progress, c, t),
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

    # ── Annulation ────────────────────────────────────────────────────────────
    def _cancel(self):
        self.cancel_event.set()
        self.cancel_btn.config(state="disabled")
        self._log("⏹  Annulation en cours…")


# ─── Point d'entrée ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    root = tk.Tk()
    ChronoSortApp(root)
    root.mainloop()
