import os
import re
import uuid
import json
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
MODE_RENOMMAGE          = "renommage"
INDEX_FILENAME          = ".chronosort_index.json"
INDEX_VERSION           = 1

MODE_LABELS = {
    MODE_TRI:       "Mode Tri",
    MODE_MIROIR:    "Mode Miroir",
    MODE_RENOMMAGE: "Mode Renommage",
}

DATE_PREFIX_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_")

ACCENT      = "#5b5ef4"
ACCENT_DARK = "#4340c4"
CLR_MUTED   = "#6b7280"
CLR_CARD_ON = "#eff6ff"
CLR_BORDER  = "#d1d5db"

SYSTEM_FILES = {
    ".DS_Store", "Thumbs.db", "desktop.ini",
    ".localized", ".Spotlight-V100", "ehthumbs.db",
    INDEX_FILENAME,
}

# ─── Catégories ───────────────────────────────────────────────────────────────
EXTENSION_CATEGORIES: dict[str, tuple[str, bool]] = {
    ".jpg":  ("Images", True),  ".jpeg": ("Images", True),
    ".png":  ("Images", True),  ".gif":  ("Images", True),
    ".bmp":  ("Images", True),  ".tiff": ("Images", True),
    ".tif":  ("Images", True),  ".webp": ("Images", True),
    ".heic": ("Images", True),  ".heif": ("Images", True),
    ".raw":  ("Images", True),  ".cr2":  ("Images", True),
    ".nef":  ("Images", True),  ".arw":  ("Images", True),
    ".mp4":  ("Vidéos", True),  ".mov":  ("Vidéos", True),
    ".avi":  ("Vidéos", True),  ".mkv":  ("Vidéos", True),
    ".wmv":  ("Vidéos", True),  ".flv":  ("Vidéos", True),
    ".webm": ("Vidéos", True),  ".m4v":  ("Vidéos", True),
    ".3gp":  ("Vidéos", True),  ".mpg":  ("Vidéos", True),
    ".mpeg": ("Vidéos", True),
    ".pdf":  ("PDF",        False),
    ".doc":  ("Word",       False), ".docx": ("Word",       False),
    ".odt":  ("Word",       False), ".rtf":  ("Word",       False),
    ".xls":  ("Excel",      False), ".xlsx": ("Excel",      False),
    ".ods":  ("Excel",      False), ".csv":  ("Excel",      False),
    ".ppt":  ("PowerPoint", False), ".pptx": ("PowerPoint", False),
    ".odp":  ("PowerPoint", False),
    ".mp3":  ("Audio", True), ".wav":  ("Audio", True),
    ".flac": ("Audio", True), ".aac":  ("Audio", True),
    ".ogg":  ("Audio", True), ".wma":  ("Audio", True),
    ".m4a":  ("Audio", True), ".opus": ("Audio", True),
    ".zip": ("Archives", False), ".rar": ("Archives", False),
    ".7z":  ("Archives", False), ".tar": ("Archives", False),
    ".gz":  ("Archives", False), ".bz2": ("Archives", False),
}

IMAGE_EXTENSIONS = {k for k, (c, _) in EXTENSION_CATEGORIES.items() if c == "Images"}


def get_category_subfolder(file_path: str, base_dir: str) -> str:
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


# ─── Utilitaire nom de fichier ─────────────────────────────────────────────────
def normalize_filename(filename: str) -> str | None:
    """
    Nettoie les préfixes date empilés (plusieurs passes Mode Tri).
    - Plusieurs préfixes → garde uniquement le premier
    - Un seul préfixe propre → retourne le nom tel quel
    - Aucun préfixe → retourne None (l'appelant ajoute la date)
    """
    m = DATE_PREFIX_RE.match(filename)
    if not m:
        return None
    first_prefix = m.group(0)
    rest = filename[len(first_prefix):]
    while True:
        m2 = DATE_PREFIX_RE.match(rest)
        if not m2:
            break
        rest = rest[len(m2.group(0)):]
    return first_prefix + rest


# ─── État de déduplication ────────────────────────────────────────────────────
class DedupState:
    def __init__(self):
        self.hashes:       dict            = {}
        self.pdf_hashes:   dict            = {}
        self.phash_tree:   pybktree.BKTree = pybktree.BKTree(lambda a, b: abs(a - b))
        self._phash_list:  list            = []
        self._phash_empty: bool            = True
        self._created:     str             = datetime.now().isoformat(timespec="seconds")

    def add(self, file_hash=None, phash=None, pdf_hash=None, path: str = ""):
        if file_hash:
            self.hashes[file_hash] = path
        if phash is not None:
            self.phash_tree.add(phash)
            self._phash_list.append(str(phash))
            self._phash_empty = False
        if pdf_hash:
            self.pdf_hashes[pdf_hash] = path

    def is_exact_duplicate(self, h: str | None) -> bool:
        return bool(h and h in self.hashes)

    def is_visual_duplicate(self, phash, threshold: int) -> bool:
        if phash is None or self._phash_empty:
            return False
        return bool(self.phash_tree.find(phash, threshold))

    def is_pdf_duplicate(self, h: str | None) -> bool:
        return bool(h and h in self.pdf_hashes)

    def destination_exists(self, file_hash: str) -> bool:
        path = self.hashes.get(file_hash, "")
        return bool(path and os.path.isfile(path))

    def to_dict(self, mode: str) -> dict:
        return {
            "version":      INDEX_VERSION,
            "mode":         mode,
            "created":      self._created,
            "last_updated": datetime.now().isoformat(timespec="seconds"),
            "file_count":   len(self.hashes),
            "hashes":       self.hashes,
            "pdf_hashes":   self.pdf_hashes,
            "phashes":      self._phash_list,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DedupState":
        state = cls()
        state.hashes     = data.get("hashes", {})
        state.pdf_hashes = data.get("pdf_hashes", {})
        state._created   = data.get("created", state._created)
        for ph_str in data.get("phashes", []):
            try:
                ph = imagehash.hex_to_hash(ph_str)
                state.phash_tree.add(ph)
                state._phash_list.append(ph_str)
                state._phash_empty = False
            except Exception:
                pass
        return state


# ─── Persistance JSON ─────────────────────────────────────────────────────────
def index_path(target_dir: str) -> str:
    return os.path.join(target_dir, INDEX_FILENAME)


def load_index(target_dir: str, mode: str, on_log) -> DedupState | None:
    path = index_path(target_dir)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        on_log("⚠️  Index illisible ou corrompu — réindexation complète.\n")
        return None
    if data.get("version") != INDEX_VERSION:
        on_log("⚠️  Index obsolète — réindexation complète.\n")
        return None
    if data.get("mode") != mode:
        label = MODE_LABELS.get(data.get("mode"), data.get("mode") or "inconnu")
        on_log(f"⚠️  Index créé en {label}, mode actuel différent — réindexation complète.\n")
        return None
    state   = DedupState.from_dict(data)
    updated = data.get("last_updated", "?")
    on_log(f"⚡ Index chargé ({len(state.hashes)} fichier(s), mis à jour le {updated})")
    on_log("   Indexation instantanée — aucun fichier relu.\n")
    return state


def save_index(target_dir: str, state: DedupState, mode: str, on_log):
    path = index_path(target_dir)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state.to_dict(mode), f, separators=(",", ":"), ensure_ascii=False)
        on_log(f"\n💾 Index mis à jour ({len(state.hashes)} fichier(s)) → {INDEX_FILENAME}")
    except Exception as e:
        on_log(f"\n⚠️  Impossible de sauvegarder l'index : {e}")


def reset_index(target_dir: str) -> bool:
    path = index_path(target_dir)
    if os.path.exists(path):
        os.remove(path)
        return True
    return False


# ─── Utilitaires communs ──────────────────────────────────────────────────────
def resolve_conflict(folder: str, filename: str) -> str:
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
    cancel_event: threading.Event,
    on_log,
    on_progress,
) -> DedupState:
    if not os.path.isdir(target_dir):
        return DedupState()
    state = load_index(target_dir, mode, on_log)
    if state is not None:
        return state
    existing = scan_dir(target_dir)
    count    = len(existing)
    if count == 0:
        on_log("📂 Destination vierge — aucun fichier existant à indexer.\n")
        return DedupState()
    on_log(f"🔍 Indexation de la destination : {count} fichier(s) déjà présent(s)…")
    on_log("   (Les doublons seront détectés même si le dossier source change.)\n")
    state = DedupState()
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
    source_dir:   str,
    target_dir:   str,
    move_files:   bool,
    threshold:    int,
    state:        DedupState,
    all_files:    list[str],
    cancel_event: threading.Event,
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

        file_hash = get_file_hash(src)
        is_exact  = state.is_exact_duplicate(file_hash)

        phash     = None
        is_visual = False
        if not is_exact and ext in IMAGE_EXTENSIONS:
            phash     = get_image_phash(src)
            is_visual = state.is_visual_duplicate(phash, threshold)

        pdf_hash = None
        is_pdf   = False
        if not is_exact and not is_visual and ext == ".pdf":
            pdf_hash = get_pdf_text_hash(src)
            is_pdf   = state.is_pdf_duplicate(pdf_hash)

        # Doublon SHA256 → suppression directe
        if is_exact:
            try:
                os.remove(src)
                on_log(f"  [SUPPRIMÉ] {filename}  (doublon exact SHA256)")
                stats["deleted"] += 1
            except Exception as e:
                on_log(f"  [ERREUR] {filename} : {e}")
                stats["error"] += 1
            continue

        # Renommage : nettoyage dates empilées + préfixage date
        normalized = normalize_filename(filename)
        if normalized is not None:
            new_name = normalized
        else:
            date     = get_exif_date(src) or get_file_date(src)
            date_str = date.strftime("%Y-%m-%d_%H-%M-%S") if date else "unknown_date"
            new_name = f"{date_str}_{filename}"

        is_soft_dup = is_visual or is_pdf
        if is_soft_dup:
            reason      = "VISUEL" if is_visual else "PDF"
            target_base = get_category_subfolder(src, doublon_dir)
            on_log(f"  [DOUBLON {reason}] {filename}")
            stats["duplicate"] += 1
        else:
            target_base = get_category_subfolder(src, target_dir)

        os.makedirs(target_base, exist_ok=True)
        dst = resolve_conflict(target_base, new_name)

        try:
            transfer(src, dst, move_files)
            if not is_soft_dup:
                on_log(f"  [OK] {filename}  →  {os.path.relpath(dst, target_dir)}")
                stats["ok"] += 1
        except Exception as e:
            on_log(f"  [ERREUR] {filename} : {e}")
            stats["error"] += 1
            continue

        state.add(
            file_hash=file_hash,
            phash=phash      if not is_visual else None,
            pdf_hash=pdf_hash if not is_pdf   else None,
            path=dst,
        )

    return stats


# ─── Mode Miroir ──────────────────────────────────────────────────────────────
def run_mode_miroir(
    source_dir:      str,
    target_dir:      str,
    move_files:      bool,
    copy_empty_dirs: bool,
    state:           DedupState,
    all_files:       list[str],
    cancel_event:    threading.Event,
    on_log,
    on_progress,
) -> dict:
    stats = {"ok": 0, "deleted": 0, "error": 0}
    total = len(all_files)

    if copy_empty_dirs:
        for root, dirs, _ in os.walk(source_dir):
            for d in dirs:
                rel     = os.path.relpath(os.path.join(root, d), source_dir)
                dst_dir = os.path.join(target_dir, rel)
                if not os.path.exists(dst_dir):
                    try:
                        os.makedirs(dst_dir, exist_ok=True)
                        on_log(f"  [DOSSIER] {rel}")
                    except Exception as e:
                        on_log(f"  [ERREUR dossier] {rel} : {e}")

    for i, src in enumerate(all_files):
        if cancel_event.is_set():
            on_log("\n⚠️  Traitement annulé par l'utilisateur.")
            return stats

        on_progress(i + 1, total, f"Traitement : {i + 1} / {total}")
        filename  = os.path.basename(src)
        file_hash = get_file_hash(src)

        if state.is_exact_duplicate(file_hash):
            if not state.destination_exists(file_hash):
                on_log(f"  [AVERT.] Hash orphelin pour {filename} — traité comme fichier unique")
            else:
                try:
                    os.remove(src)
                    on_log(f"  [SUPPRIMÉ] {filename}  (doublon exact SHA256)")
                    stats["deleted"] += 1
                except Exception as e:
                    on_log(f"  [ERREUR] {filename} : {e}")
                    stats["error"] += 1
                continue

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


# ─── Mode Renommage ───────────────────────────────────────────────────────────

def resolve_token(fmt: str, path: str, counter: int, padding: int) -> str:
    """
    Remplace tous les tokens du format par leurs valeurs pour un fichier donné.
    Si {ext} absent du format, l'extension originale est automatiquement conservée.
    """
    filename    = os.path.basename(path)
    name_no_ext = os.path.splitext(filename)[0]
    ext         = os.path.splitext(filename)[1]       # avec le point : ".jpg"
    ext_clean   = ext.lstrip(".")                      # sans le point  : "jpg"

    date      = get_exif_date(path) or get_file_date(path)
    date_str  = date.strftime("%Y-%m-%d") if date else "unknown_date"
    heure_str = date.strftime("%H-%M-%S") if date else "00-00-00"

    dossier     = os.path.basename(os.path.dirname(path)) or "racine"
    counter_str = str(counter).zfill(padding)

    new_name = fmt
    new_name = new_name.replace("{date}",      date_str)
    new_name = new_name.replace("{heure}",     heure_str)
    new_name = new_name.replace("{nom}",       name_no_ext)
    new_name = new_name.replace("{dossier}",   dossier)
    new_name = new_name.replace("{compteur}",  counter_str)

    if "{ext}" in fmt:
        new_name = new_name.replace("{ext}", ext_clean)
    elif ext:
        new_name = new_name + ext   # conservation automatique de l'extension

    return new_name


def compute_counter_map(
    files_by_folder: dict[str, list[str]],
    order: str,
) -> dict[str, int]:
    """
    Attribue un compteur à chaque fichier au sein de son dossier, trié par date.
    order : "asc"  → 0001 = plus ancien
            "desc" → 0001 = plus récent
    """
    result = {}
    for folder, paths in files_by_folder.items():
        dated = []
        for p in paths:
            d = get_exif_date(p) or get_file_date(p) or datetime.min
            dated.append((d, p))
        dated.sort(key=lambda x: x[0], reverse=(order == "desc"))
        for i, (_, p) in enumerate(dated):
            result[p] = i + 1
    return result


def preview_renommage(source_dir: str, fmt: str, order: str) -> list[tuple[str, str]]:
    """
    Calcule un aperçu de renommage sur 5 fichiers représentatifs.
    Essaie de sélectionner des fichiers dans des sous-dossiers différents.
    """
    if not fmt.strip() or not os.path.isdir(source_dir):
        return []

    all_files = scan_dir(source_dir)
    if not all_files:
        return []

    files_by_folder: dict[str, list[str]] = {}
    for p in all_files:
        files_by_folder.setdefault(os.path.dirname(p), []).append(p)

    # Sélection de 5 fichiers répartis dans différents dossiers
    sample: list[str] = []
    folders = list(files_by_folder.keys())
    idx = 0
    while len(sample) < 5:
        added = False
        for folder in folders:
            if len(sample) >= 5:
                break
            if idx < len(files_by_folder[folder]):
                sample.append(files_by_folder[folder][idx])
                added = True
        if not added:
            break
        idx += 1

    counter_map = compute_counter_map(files_by_folder, order)
    padding_map = {f: max(4, len(str(len(ps)))) for f, ps in files_by_folder.items()}

    result = []
    for p in sample:
        folder  = os.path.dirname(p)
        counter = counter_map[p]
        padding = padding_map[folder]
        try:
            new_name = resolve_token(fmt, p, counter, padding)
            result.append((os.path.basename(p), new_name))
        except Exception:
            result.append((os.path.basename(p), "⚠️ Format invalide"))

    return result


def run_mode_renommage(
    source_dir:   str,
    fmt:          str,
    order:        str,
    all_files:    list[str],
    cancel_event: threading.Event,
    on_log,
    on_progress,
) -> dict:
    """
    Renomme les fichiers sur place selon le format défini par l'utilisateur.
    - Compteur chronologique par sous-dossier
    - Doublons SHA256 → suppression
    - Même nom / contenu différent → suffixe numérique
    - Renommage en deux phases (temp UUID → final) pour éviter les conflits circulaires
    """
    stats = {"renamed": 0, "deleted": 0, "skipped": 0, "error": 0}

    if not fmt.strip():
        on_log("❌ Format de renommage vide.")
        return stats

    total = len(all_files)
    on_log(f"  Format : {fmt}\n")

    # ── Groupement par dossier + compteurs ────────────────────────────────────
    files_by_folder: dict[str, list[str]] = {}
    for p in all_files:
        files_by_folder.setdefault(os.path.dirname(p), []).append(p)

    counter_map = compute_counter_map(files_by_folder, order)
    padding_map = {f: max(4, len(str(len(ps)))) for f, ps in files_by_folder.items()}

    # ── Construction du plan de renommage ─────────────────────────────────────
    # plan_items : list of (src, dst | None, action)
    # action     : "rename" | "delete" | "skip"
    plan_items: list[tuple[str, str | None, str]] = []

    for i, src in enumerate(all_files):
        if cancel_event.is_set():
            on_log("\n⚠️  Traitement annulé par l'utilisateur.")
            return stats
        on_progress(i + 1, total, f"Analyse : {i + 1} / {total}")

    # Par dossier : détecter les conflits de noms
    for folder, paths in files_by_folder.items():
        padding = padding_map[folder]

        desired: dict[str, str] = {}
        for src in paths:
            desired[src] = resolve_token(fmt, src, counter_map[src], padding)

        by_name: dict[str, list[str]] = {}
        for src, name in desired.items():
            by_name.setdefault(name, []).append(src)

        for new_name, srcs in by_name.items():
            if len(srcs) == 1:
                src = srcs[0]
                dst = os.path.join(folder, new_name)
                if os.path.normcase(src) == os.path.normcase(dst):
                    plan_items.append((src, dst, "skip"))
                else:
                    plan_items.append((src, dst, "rename"))
            else:
                # Plusieurs fichiers → même nom désiré
                hash_seen: dict[str, str] = {}
                suffix_n  = 1
                first     = True
                for src in srcs:
                    h = get_file_hash(src)
                    if h and h in hash_seen:
                        plan_items.append((src, None, "delete"))
                    else:
                        if h:
                            hash_seen[h] = src
                        if first:
                            dst   = os.path.join(folder, new_name)
                            first = False
                        else:
                            base, ext = os.path.splitext(new_name)
                            dst = os.path.join(folder, f"{base}_{suffix_n}{ext}")
                            suffix_n += 1
                        if os.path.normcase(src) == os.path.normcase(dst):
                            plan_items.append((src, dst, "skip"))
                        else:
                            plan_items.append((src, dst, "rename"))

    rn = sum(1 for _, _, a in plan_items if a == "rename")
    dl = sum(1 for _, _, a in plan_items if a == "delete")
    sk = sum(1 for _, _, a in plan_items if a == "skip")
    on_log(f"  Plan : {rn} renommage(s) · {dl} suppression(s) · {sk} déjà correct(s)\n")

    # ── Exécution des suppressions ────────────────────────────────────────────
    for src, _, action in plan_items:
        if cancel_event.is_set():
            return stats
        if action != "delete":
            continue
        try:
            os.remove(src)
            on_log(f"  [SUPPRIMÉ] {os.path.basename(src)}  (doublon exact)")
            stats["deleted"] += 1
        except Exception as e:
            on_log(f"  [ERREUR] {os.path.basename(src)} : {e}")
            stats["error"] += 1

    # ── Renommage deux phases ──────────────────────────────────────────────────
    # Phase A : src → temp UUID (évite les conflits circulaires)
    temp_map: dict[str, str] = {}
    rename_items = [(s, d) for s, d, a in plan_items if a == "rename"]

    for src, _ in rename_items:
        if cancel_event.is_set():
            for orig, tmp in temp_map.items():
                try:
                    os.rename(tmp, orig)
                except Exception:
                    pass
            on_log("\n⚠️  Traitement annulé — renommages temporaires annulés.")
            return stats
        tmp = os.path.join(os.path.dirname(src), f"__cst_{uuid.uuid4().hex}")
        try:
            os.rename(src, tmp)
            temp_map[src] = tmp
        except Exception as e:
            on_log(f"  [ERREUR phase 1] {os.path.basename(src)} : {e}")
            stats["error"] += 1

    # Phase B : temp → nom final
    for src, dst in rename_items:
        tmp = temp_map.get(src)
        if tmp is None or not os.path.exists(tmp):
            continue
        final_dst = dst
        if os.path.exists(final_dst):
            final_dst = resolve_conflict(os.path.dirname(dst), os.path.basename(dst))
        try:
            os.rename(tmp, final_dst)
            new_n = os.path.basename(final_dst)
            on_log(f"  [RENOMMÉ] {os.path.basename(src)}  →  {new_n}")
            stats["renamed"] += 1
        except Exception as e:
            on_log(f"  [ERREUR phase 2] {os.path.basename(src)} : {e}")
            stats["error"] += 1

    stats["skipped"] = sk
    return stats


def process_renommage(
    source_dir:   str,
    fmt:          str,
    order:        str,
    cancel_event: threading.Event,
    callbacks:    dict,
):
    on_progress = callbacks["on_progress"]
    on_log      = callbacks["on_log"]
    on_done     = callbacks["on_done"]

    if not os.path.isdir(source_dir):
        on_log("❌ Dossier source invalide ou introuvable.")
        on_done(None)
        return

    all_files = scan_dir(source_dir)
    on_log(f"📂 {len(all_files)} fichier(s) trouvé(s) — Mode Renommage — démarrage…\n")

    if not all_files:
        on_log("⚠️  Aucun fichier à traiter.")
        on_done({"renamed": 0, "deleted": 0, "skipped": 0, "error": 0})
        return

    stats = run_mode_renommage(source_dir, fmt, order, all_files, cancel_event, on_log, on_progress)
    on_done(stats)


# ─── Orchestrateur Tri / Miroir ───────────────────────────────────────────────
def process_files(
    source_dir:      str,
    target_dir:      str,
    mode:            str,
    move_files:      bool,
    threshold:       int,
    copy_empty_dirs: bool,
    cancel_event:    threading.Event,
    callbacks:       dict,
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

    state = index_destination(target_dir, mode, cancel_event, on_log, on_progress)
    if cancel_event.is_set():
        on_log("⚠️  Annulé pendant l'indexation.")
        on_done(None)
        return

    on_progress(0, 1, "")

    all_files  = scan_dir(source_dir)
    mode_label = MODE_LABELS.get(mode, mode)
    on_log(f"📂 {len(all_files)} fichier(s) trouvé(s) — {mode_label} — démarrage…\n")

    if not all_files:
        on_log("⚠️  Aucun fichier à traiter.")
        save_index(target_dir, state, mode, on_log)
        on_done({"ok": 0, "deleted": 0, "duplicate": 0, "error": 0} if mode == MODE_TRI
                else {"ok": 0, "deleted": 0, "error": 0})
        return

    if mode == MODE_TRI:
        stats = run_mode_tri(
            source_dir, target_dir, move_files, threshold,
            state, all_files, cancel_event, on_log, on_progress,
        )
    else:
        stats = run_mode_miroir(
            source_dir, target_dir, move_files, copy_empty_dirs,
            state, all_files, cancel_event, on_log, on_progress,
        )

    if move_files:
        cleanup_empty_dirs(source_dir, on_log)

    save_index(target_dir, state, mode, on_log)
    on_done(stats)


# ─── Interface graphique ───────────────────────────────────────────────────────
class ChronoSortApp:
    def __init__(self, root: tk.Tk):
        self.root              = root
        self.cancel_event      = threading.Event()
        self._preview_after_id = None
        self._setup_window()
        self._setup_styles()
        self._build_ui()

    # ── Fenêtre ───────────────────────────────────────────────────────────────
    def _setup_window(self):
        self.root.title("ChronoSort")
        self.root.minsize(700, 580)
        self.root.resizable(True, True)
        self.root.update_idletasks()
        w, h = 800, 780
        x = (self.root.winfo_screenwidth()  - w) // 2
        y = (self.root.winfo_screenheight() - h) // 2
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(5, weight=1)

    # ── Styles ────────────────────────────────────────────────────────────────
    def _setup_styles(self):
        s = ttk.Style()
        s.theme_use("clam")
        s.configure("TFrame",      background="#f9fafb")
        s.configure("TLabel",      background="#f9fafb", foreground="#111827")
        s.configure("TLabelframe", background="#f9fafb", foreground="#374151",
                    bordercolor=CLR_BORDER, relief="solid", borderwidth=1)
        s.configure("TLabelframe.Label", background="#f9fafb", foreground="#374151",
                    font=("Segoe UI", 9, "bold"))
        s.configure("TCheckbutton", background="#f9fafb", foreground="#111827")
        s.configure("TSpinbox",     fieldbackground="white", foreground="#111827")
        s.configure("TEntry",       fieldbackground="white", foreground="#111827")
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
        s.configure("Token.TButton",
                    background="#ede9fe", foreground="#5b21b6",
                    font=("Segoe UI", 8, "bold"), borderwidth=1, relief="solid")
        s.map("Token.TButton",
              background=[("active", "#ddd6fe")])
        s.configure("Warn.TButton",
                    background="#fef3c7", foreground="#92400e",
                    font=("Segoe UI", 8), borderwidth=1, relief="solid")
        s.map("Warn.TButton",
              background=[("active", "#fde68a"), ("disabled", "#f9fafb")])
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
        tk.Label(header, text="📸  ChronoSort",
                 bg=ACCENT, fg="white", font=("Segoe UI", 14, "bold"), anchor="w"
                 ).grid(row=0, column=0, sticky="w", padx=16, pady=(10, 2))
        tk.Label(header, text="Tri  ·  Déduplication  ·  Organisation automatique",
                 bg=ACCENT, fg="#c7d2fe", font=("Segoe UI", 8), anchor="w"
                 ).grid(row=1, column=0, sticky="w", padx=18, pady=(0, 10))

    # ── Dossiers ──────────────────────────────────────────────────────────────
    def _build_paths_frame(self):
        frame = ttk.LabelFrame(self.root, text="  Dossiers", padding=(12, 8))
        frame.grid(row=1, column=0, sticky="ew", padx=12, pady=(10, 4))
        frame.columnconfigure(1, weight=1)

        self.source_var = tk.StringVar()
        self.target_var = tk.StringVar()

        ttk.Label(frame, text="Source :", font=("Segoe UI", 9)).grid(row=0, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.source_var, font=("Segoe UI", 9)).grid(
            row=0, column=1, sticky="ew", padx=8)
        ttk.Button(frame, text="Parcourir…", command=self._pick_source).grid(row=0, column=2)

        # Destination — masquée en Mode Renommage
        self._lbl_dest = ttk.Label(frame, text="Destination :", font=("Segoe UI", 9))
        self._lbl_dest.grid(row=1, column=0, sticky="w", pady=(6, 0))
        self._ent_dest = ttk.Entry(frame, textvariable=self.target_var, font=("Segoe UI", 9))
        self._ent_dest.grid(row=1, column=1, sticky="ew", padx=8, pady=(6, 0))
        self._btn_dest = ttk.Button(frame, text="Parcourir…", command=self._pick_target)
        self._btn_dest.grid(row=1, column=2, pady=(6, 0))

        self._note_frame = ttk.Frame(frame)
        self._note_frame.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(10, 2))
        self._note_frame.columnconfigure(0, weight=1)
        ttk.Label(
            self._note_frame,
            text="ℹ️  Même destination réutilisable d'une passe à l'autre."
                 " Un index est sauvegardé automatiquement pour accélérer les passes suivantes.",
            foreground=CLR_MUTED, font=("Segoe UI", 8), wraplength=520, justify="left",
        ).grid(row=0, column=0, sticky="w")
        ttk.Button(
            self._note_frame, text="🗑  Réinitialiser l'index",
            style="Warn.TButton", command=self._reset_index, width=22,
        ).grid(row=0, column=1, padx=(8, 0), sticky="e")

    # ── Sélection du mode ─────────────────────────────────────────────────────
    def _build_mode_frame(self):
        frame = ttk.LabelFrame(self.root, text="  Mode de fonctionnement", padding=(12, 8))
        frame.grid(row=2, column=0, sticky="ew", padx=12, pady=4)
        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        frame.columnconfigure(2, weight=1)

        self.mode_var = tk.StringVar(value=MODE_TRI)

        self.card_tri = tk.Frame(frame, bg=CLR_CARD_ON, bd=2, relief="solid", cursor="hand2")
        self.card_tri.grid(row=0, column=0, sticky="nsew", padx=(0, 4), pady=2)
        self.card_tri.bind("<Button-1>", lambda e: self._set_mode(MODE_TRI))
        tk.Radiobutton(self.card_tri, text="✦  Mode Tri", variable=self.mode_var, value=MODE_TRI,
                       font=("Segoe UI", 10, "bold"), bg=CLR_CARD_ON, activebackground=CLR_CARD_ON,
                       fg=ACCENT, command=lambda: self._set_mode(MODE_TRI), cursor="hand2",
                       ).pack(anchor="w", padx=10, pady=(10, 2))
        tk.Label(self.card_tri,
                 text="Pour les dossiers sans organisation.\n"
                      "Renomme par date, nettoie les noms,\n"
                      "classe par catégorie. Supprime les\n"
                      "doublons exacts. pHash/PDF → Doublon/.",
                 bg=CLR_CARD_ON, fg="#374151", font=("Segoe UI", 8), justify="left",
                 ).pack(anchor="w", padx=20, pady=(0, 12))

        self.card_miroir = tk.Frame(frame, bg="white", bd=1, relief="solid", cursor="hand2")
        self.card_miroir.grid(row=0, column=1, sticky="nsew", padx=4, pady=2)
        self.card_miroir.bind("<Button-1>", lambda e: self._set_mode(MODE_MIROIR))
        tk.Radiobutton(self.card_miroir, text="⟺  Mode Miroir", variable=self.mode_var, value=MODE_MIROIR,
                       font=("Segoe UI", 10, "bold"), bg="white", activebackground=CLR_CARD_ON,
                       fg=CLR_MUTED, command=lambda: self._set_mode(MODE_MIROIR), cursor="hand2",
                       ).pack(anchor="w", padx=10, pady=(10, 2))
        tk.Label(self.card_miroir,
                 text="Pour les dossiers déjà organisés.\n"
                      "Réplique l'arborescence à l'identique.\n"
                      "Supprime les doublons exacts.\n"
                      "Aucun renommage.",
                 bg="white", fg="#374151", font=("Segoe UI", 8), justify="left",
                 ).pack(anchor="w", padx=20, pady=(0, 12))

        self.card_renommage = tk.Frame(frame, bg="white", bd=1, relief="solid", cursor="hand2")
        self.card_renommage.grid(row=0, column=2, sticky="nsew", padx=(4, 0), pady=2)
        self.card_renommage.bind("<Button-1>", lambda e: self._set_mode(MODE_RENOMMAGE))
        tk.Radiobutton(self.card_renommage, text="✏  Mode Renommage", variable=self.mode_var, value=MODE_RENOMMAGE,
                       font=("Segoe UI", 10, "bold"), bg="white", activebackground=CLR_CARD_ON,
                       fg=CLR_MUTED, command=lambda: self._set_mode(MODE_RENOMMAGE), cursor="hand2",
                       ).pack(anchor="w", padx=10, pady=(10, 2))
        tk.Label(self.card_renommage,
                 text="Renomme sur place selon un\nformat libre avec tokens.\nGestion des doublons intégrée.",
                 bg="white", fg="#374151", font=("Segoe UI", 8), justify="left",
                 ).pack(anchor="w", padx=20, pady=(0, 12))

    def _set_mode(self, mode: str):
        self.mode_var.set(mode)
        self._style_card(self.card_tri,       selected=(mode == MODE_TRI))
        self._style_card(self.card_miroir,    selected=(mode == MODE_MIROIR))
        self._style_card(self.card_renommage, selected=(mode == MODE_RENOMMAGE))

        self.frame_tri_opts.grid_remove()
        self.frame_miroir_opts.grid_remove()
        self.frame_renommage_opts.grid_remove()

        if mode == MODE_TRI:
            self.frame_tri_opts.grid()
        elif mode == MODE_MIROIR:
            self.frame_miroir_opts.grid()
        else:
            self.frame_renommage_opts.grid()

        is_renommage = (mode == MODE_RENOMMAGE)
        for w in (self._lbl_dest, self._ent_dest, self._btn_dest, self._note_frame):
            if is_renommage:
                w.grid_remove()
            else:
                w.grid()

        if is_renommage:
            self._schedule_preview()

    def _style_card(self, card: tk.Frame, selected: bool):
        bg = CLR_CARD_ON if selected else "white"
        card.config(bg=bg, bd=2 if selected else 1)
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
        self._move_check = ttk.Checkbutton(
            frame, text="Déplacer les fichiers (au lieu de copier)",
            variable=self.move_var,
        )
        self._move_check.grid(row=0, column=0, columnspan=3, sticky="w")

        # ── Options Mode Tri ───────────────────────────────────────────────────
        self.frame_tri_opts = ttk.Frame(frame)
        self.frame_tri_opts.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(4, 0))
        self.frame_tri_opts.columnconfigure(0, weight=1)

        ttk.Separator(self.frame_tri_opts, orient="horizontal").grid(
            row=0, column=0, columnspan=3, sticky="ew", pady=(6, 8))
        ttk.Label(self.frame_tri_opts, text="Seuil similarité visuelle :",
                  font=("Segoe UI", 9)).grid(row=1, column=0, sticky="w")
        self.threshold_var = tk.IntVar(value=DEFAULT_PHASH_THRESHOLD)
        ttk.Spinbox(self.frame_tri_opts, from_=0, to=10,
                    textvariable=self.threshold_var, width=5, state="readonly",
                    ).grid(row=1, column=1, sticky="w", padx=8)
        ttk.Label(self.frame_tri_opts, text="0 = identique strict   ·   10 = très permissif",
                  foreground=CLR_MUTED, font=("Segoe UI", 8)).grid(row=1, column=2, sticky="w")

        # ── Options Mode Miroir ────────────────────────────────────────────────
        self.frame_miroir_opts = ttk.Frame(frame)
        self.frame_miroir_opts.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(4, 0))
        self.frame_miroir_opts.columnconfigure(0, weight=1)
        self.frame_miroir_opts.grid_remove()

        ttk.Separator(self.frame_miroir_opts, orient="horizontal").grid(
            row=0, column=0, sticky="ew", pady=(6, 8))
        self.copy_empty_dirs_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(self.frame_miroir_opts,
                        text="Reproduire les dossiers vides de la source",
                        variable=self.copy_empty_dirs_var,
                        ).grid(row=1, column=0, sticky="w")
        ttk.Label(self.frame_miroir_opts,
                  text="   Recrée dans la destination les dossiers vides de la source,"
                       " pour conserver l'organisation structurelle.",
                  foreground=CLR_MUTED, font=("Segoe UI", 8), wraplength=620, justify="left",
                  ).grid(row=2, column=0, sticky="w", pady=(2, 0))

        # ── Options Mode Renommage ─────────────────────────────────────────────
        self.frame_renommage_opts = ttk.Frame(frame)
        self.frame_renommage_opts.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(4, 0))
        self.frame_renommage_opts.columnconfigure(1, weight=1)
        self.frame_renommage_opts.grid_remove()

        ttk.Separator(self.frame_renommage_opts, orient="horizontal").grid(
            row=0, column=0, columnspan=3, sticky="ew", pady=(6, 8))

        # Champ format
        ttk.Label(self.frame_renommage_opts, text="Format :",
                  font=("Segoe UI", 9)).grid(row=1, column=0, sticky="w")
        self.format_var = tk.StringVar(value="{date}_{heure}_{nom}")
        self.format_entry = ttk.Entry(
            self.frame_renommage_opts, textvariable=self.format_var,
            font=("Consolas", 9), width=42)
        self.format_entry.grid(row=1, column=1, sticky="ew", padx=8)
        self.format_var.trace_add("write", lambda *_: self._schedule_preview())

        ttk.Label(
            self.frame_renommage_opts,
            text="L'extension est conservée automatiquement si {ext} est absent du format.",
            foreground=CLR_MUTED, font=("Segoe UI", 8),
        ).grid(row=2, column=1, sticky="w", padx=8, pady=(2, 6))

        # Boutons tokens
        token_frame = ttk.Frame(self.frame_renommage_opts)
        token_frame.grid(row=3, column=0, columnspan=3, sticky="w", pady=(0, 8))
        ttk.Label(token_frame, text="Tokens :", font=("Segoe UI", 9)).pack(side="left", padx=(0, 8))
        for token in ("{date}", "{heure}", "{nom}", "{ext}", "{compteur}", "{dossier}"):
            ttk.Button(
                token_frame, text=token, style="Token.TButton",
                command=lambda t=token: self._insert_token(t),
            ).pack(side="left", padx=2)

        # Ordre du compteur
        order_frame = ttk.Frame(self.frame_renommage_opts)
        order_frame.grid(row=4, column=0, columnspan=3, sticky="w", pady=(0, 8))
        ttk.Label(order_frame, text="Ordre du compteur :",
                  font=("Segoe UI", 9)).pack(side="left", padx=(0, 8))
        self.order_var = tk.StringVar(value="asc")
        order_combo = ttk.Combobox(
            order_frame, textvariable=self.order_var, state="readonly", width=32,
            values=["asc — 0001 = plus ancien (croissant)",
                    "desc — 0001 = plus récent (décroissant)"],
        )
        order_combo.current(0)
        order_combo.pack(side="left")
        order_combo.bind("<<ComboboxSelected>>", lambda _: self._schedule_preview())

        # Aperçu
        ttk.Label(self.frame_renommage_opts,
                  text="Aperçu (5 fichiers représentatifs) :",
                  font=("Segoe UI", 9)).grid(row=5, column=0, columnspan=3, sticky="w", pady=(4, 4))

        preview_frame = ttk.Frame(self.frame_renommage_opts)
        preview_frame.grid(row=6, column=0, columnspan=3, sticky="ew")
        preview_frame.columnconfigure(0, weight=1)

        self.preview_tree = ttk.Treeview(
            preview_frame,
            columns=("avant", "apres"),
            show="headings",
            height=5,
        )
        self.preview_tree.heading("avant", text="Nom actuel")
        self.preview_tree.heading("apres", text="→  Nouveau nom")
        self.preview_tree.column("avant", width=300, anchor="w")
        self.preview_tree.column("apres", width=300, anchor="w")
        self.preview_tree.grid(row=0, column=0, sticky="ew")

        self.source_var.trace_add("write", lambda *_: self._schedule_preview())

    # ── Contrôles ─────────────────────────────────────────────────────────────
    def _build_controls(self):
        frame = ttk.Frame(self.root)
        frame.grid(row=4, column=0, sticky="ew", padx=12, pady=(6, 2))
        frame.columnconfigure(2, weight=1)

        self.start_btn = ttk.Button(frame, text="▶  Lancer", style="Accent.TButton",
                                    command=self._start, width=14)
        self.start_btn.grid(row=0, column=0, padx=(0, 6), pady=(0, 8))

        self.cancel_btn = ttk.Button(frame, text="⏹  Annuler", style="Cancel.TButton",
                                     command=self._cancel, state="disabled", width=14)
        self.cancel_btn.grid(row=0, column=1, padx=(0, 12), pady=(0, 8))

        self.progress_label = ttk.Label(frame, text="", foreground=CLR_MUTED, font=("Segoe UI", 8))
        self.progress_label.grid(row=0, column=2, sticky="w", pady=(0, 8))

        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(frame, variable=self.progress_var,
                                             maximum=100, mode="determinate",
                                             style="Horizontal.TProgressbar")
        self.progress_bar.grid(row=1, column=0, columnspan=3, sticky="ew")

    # ── Journal ───────────────────────────────────────────────────────────────
    def _build_log_frame(self):
        frame = ttk.LabelFrame(self.root, text="  Journal", padding=(8, 6))
        frame.grid(row=5, column=0, sticky="nsew", padx=12, pady=(6, 10))
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

    def _reset_index(self):
        target = self.target_var.get().strip()
        if not target:
            self._log("❌ Sélectionnez d'abord un dossier destination.")
            return
        if reset_index(target):
            self._log("🗑  Index réinitialisé — la prochaine passe effectuera un scan complet.")
        else:
            self._log("ℹ️  Aucun index trouvé dans ce dossier destination.")

    # ── Aperçu renommage ──────────────────────────────────────────────────────
    def _insert_token(self, token: str):
        pos = self.format_entry.index(tk.INSERT)
        self.format_entry.insert(pos, token)
        self.format_entry.focus()

    def _schedule_preview(self):
        if self._preview_after_id:
            self.root.after_cancel(self._preview_after_id)
        self._preview_after_id = self.root.after(400, self._launch_preview)

    def _launch_preview(self):
        source = self.source_var.get().strip()
        fmt    = self.format_var.get().strip()
        order  = "asc" if self.order_var.get().startswith("asc") else "desc"
        threading.Thread(
            target=self._compute_preview_bg,
            args=(source, fmt, order),
            daemon=True,
        ).start()

    def _compute_preview_bg(self, source: str, fmt: str, order: str):
        rows = preview_renommage(source, fmt, order)
        self.root.after(0, self._refresh_preview_table, rows)

    def _refresh_preview_table(self, rows: list[tuple[str, str]]):
        for item in self.preview_tree.get_children():
            self.preview_tree.delete(item)
        if not rows:
            self.preview_tree.insert("", "end", values=("—", "Sélectionnez un dossier source"))
            return
        for old, new in rows:
            self.preview_tree.insert("", "end", values=(old, new))

    # ── Callbacks ─────────────────────────────────────────────────────────────
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
            if "renamed" in stats:
                self._log(
                    f"\n{sep}\n"
                    f"  ✏️   Renommés   : {stats['renamed']}\n"
                    f"  🗑️   Supprimés  : {stats['deleted']}\n"
                    f"  ⏭️   Ignorés    : {stats['skipped']}\n"
                    f"  ❌  Erreurs    : {stats['error']}\n"
                    f"{sep}"
                )
            elif "duplicate" in stats:
                self._log(
                    f"\n{sep}\n"
                    f"  ✅  Triés      : {stats['ok']}\n"
                    f"  🗑️   Supprimés  : {stats['deleted']}\n"
                    f"  📋  Doublon/   : {stats['duplicate']}\n"
                    f"  ❌  Erreurs    : {stats['error']}\n"
                    f"{sep}"
                )
            else:
                self._log(
                    f"\n{sep}\n"
                    f"  ✅  Copiés     : {stats['ok']}\n"
                    f"  🗑️   Supprimés  : {stats['deleted']}\n"
                    f"  ❌  Erreurs    : {stats['error']}\n"
                    f"{sep}"
                )
        self.progress_label.config(text="Terminé !" if stats is not None else "Annulé.")

    # ── Lancement ─────────────────────────────────────────────────────────────
    def _start(self):
        source = self.source_var.get().strip()
        target = self.target_var.get().strip()
        mode   = self.mode_var.get()

        if not source:
            self._log("❌ Veuillez sélectionner un dossier source.")
            return
        if mode != MODE_RENOMMAGE and not target:
            self._log("❌ Veuillez sélectionner un dossier destination.")
            return
        if mode == MODE_RENOMMAGE and not self.format_var.get().strip():
            self._log("❌ Veuillez définir un format de renommage.")
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

        if mode == MODE_RENOMMAGE:
            order = "asc" if self.order_var.get().startswith("asc") else "desc"
            threading.Thread(
                target=process_renommage,
                args=(source, self.format_var.get().strip(), order,
                      self.cancel_event, callbacks),
                daemon=True,
            ).start()
        else:
            threading.Thread(
                target=process_files,
                args=(source, target, mode,
                      self.move_var.get(),
                      self.threshold_var.get(),
                      self.copy_empty_dirs_var.get(),
                      self.cancel_event, callbacks),
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
