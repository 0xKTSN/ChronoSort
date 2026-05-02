# 📸 ChronoSort

> Outil Python pour trier, normaliser et dédupliquer automatiquement
> tous types de fichiers (photos, documents, etc.) avec priorité aux
> métadonnées réelles.

---

## 🚀 Objectif

ChronoSort permet de :

- Aplatir une arborescence de dossiers
- Renommer les fichiers avec une date fiable
- Trier chronologiquement automatiquement
- Détecter et isoler les doublons (exact + visuel)
- Nettoyer les dossiers vides après déplacement
- Ignorer les fichiers système (`.DS_Store`, `Thumbs.db`, etc.)

---

## 🧠 Fonctionnement

1. **📅 Date :**
   - EXIF via API publique `getexif()` (priorité)
   - Fallback : date de modification du fichier

2. **🏷️ Nom :** `YYYY-MM-DD_HH-MM-SS_nom.ext`

3. **🔍 Déduplication :**
   - SHA256 — doublon exact (tous fichiers)
   - pHash via BK-tree — doublon visuel (images uniquement, O(log n))

4. **📁 Organisation :**
   - Fichiers uniques → racine de la destination
   - Doublons → `/Doublon`

---

## 📦 Installation (Python)

Nécessite **Python 3.10+**.

```bash
pip install -r requirements.txt
```

---

## ▶️ Utilisation (script Python)

```bash
python main.py
```

L'interface graphique permet de :

- Choisir les dossiers source et destination
- Activer le mode déplacement (au lieu de copie)
- Régler le seuil de similarité visuelle (0 = strict · 10 = permissif)
- Suivre la progression en temps réel
- Annuler le traitement à tout moment

---

## 🪟 Générer un exécutable Windows (.exe)

### Prérequis

- Python installé et accessible depuis le terminal
- Dépendances installées (`pip install -r requirements.txt`)
- (Optionnel) une icône au format `.ico` dans le même dossier que `main.py`

### Commande

Depuis le dossier contenant `main.py` :

```bash
python -m PyInstaller --onefile --windowed --name "ChronoSort" --icon="icon.ico" main.py
```

> ℹ️ Si tu n'as pas d'icône, retire simplement `--icon="icon.ico"` de la commande.

### Résultat

Le fichier `ChronoSort.exe` se trouve dans le dossier `dist/` généré automatiquement.
Il est autonome et ne nécessite pas Python pour fonctionner.

### Notes importantes

| Point | Détail |
|---|---|
| Taille | ~30–60 Mo (Python + dépendances embarqués) |
| Premier lancement | 3–5 secondes (décompression en temp) — c'est normal |
| Antivirus | Windows Defender peut signaler un faux positif — autoriser manuellement |
| Portabilité | L'`.exe` généré sur Windows ne fonctionne que sur Windows |

### Dossiers générés par PyInstaller (peuvent être supprimés)

```
build/            ← fichiers intermédiaires de compilation
dist/             ← contient le .exe final
ChronoSort.spec   ← fichier de configuration PyInstaller
```

---

## ⚠️ Limites

- Détection visuelle : images uniquement (pHash)
- Sur très gros volumes (> 100 000 fichiers), le pHash reste le goulot d'étranglement

---

## 📜 Licence

MIT — libre d'utilisation et de modification

---

## 🤝 Contribution

Les contributions sont les bienvenues :

- Amélioration des performances sur gros volumes
- Support de nouveaux formats de métadonnées (vidéo, audio)
- Optimisation du seuil pHash adaptatif
