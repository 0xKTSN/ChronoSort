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
- Détecter et isoler les doublons (exact SHA256 + visuel pHash + contenu PDF)
- Supprimer automatiquement les doublons exacts (optionnel)
- Organiser les fichiers par catégorie dans la destination
- Nettoyer les dossiers vides après déplacement
- Ignorer les fichiers système (`.DS_Store`, `Thumbs.db`, etc.)

---

## 🧠 Fonctionnement

### 1. 📅 Date de référence
- EXIF via API publique `getexif()` (priorité)
- Fallback : date de modification du fichier

### 2. 🏷️ Renommage
`YYYY-MM-DD_HH-MM-SS_nom_original.ext`

### 3. 🔍 Déduplication

| Méthode | Scope | Action par défaut | Si option activée |
|---|---|---|---|
| SHA256 | Tous fichiers | Déplacement vers `Doublon/` | **Suppression directe** |
| pHash | Images uniquement | Déplacement vers `Doublon/` | Déplacement vers `Doublon/` |
| Hash texte | PDFs uniquement | Déplacement vers `Doublon/` | Déplacement vers `Doublon/` |

> Les doublons visuels (pHash) et PDF ne sont **jamais supprimés automatiquement**,
> même si l'option de suppression des doublons exacts est activée — ils sont toujours
> déplacés vers `Doublon/` pour vérification manuelle.

### 4. 📁 Organisation automatique par catégorie

Les fichiers uniques sont triés dans la destination, les doublons non exacts dans `Doublon/`,
selon la même structure :

```
destination/
├── Images/
│   ├── JPG/
│   ├── PNG/
│   ├── HEIC/
│   └── ...
├── Vidéos/
│   ├── MP4/
│   ├── MKV/
│   └── ...
├── PDF/
├── Word/
├── Excel/
├── PowerPoint/
├── Audio/
│   ├── MP3/
│   ├── FLAC/
│   └── ...
├── Archives/
├── Autres/
└── Doublon/
    ├── Images/
    │   ├── JPG/
    │   └── ...
    ├── PDF/
    └── ...
```

> Les dossiers ne sont créés que si des fichiers correspondants sont présents.

### 5. 🔄 Indexation de la destination au démarrage

À chaque lancement, ChronoSort commence par scanner les fichiers **déjà présents**
dans le dossier de destination et les intègre dans les structures de déduplication.
Cela signifie que **vous pouvez réutiliser le même dossier de destination à chaque
passe**, même si le dossier source change — aucun doublon ne sera introduit entre
deux sessions.

Le journal affiche explicitement cette phase :
```
🔍 Indexation de la destination : N fichier(s) déjà présent(s)…
   (Les doublons avec ces fichiers seront détectés même si la source change.)
✅ Indexation terminée — N fichier(s) référencé(s).
```

---

## ⚠️ Recommandation importante

> **Commencer avec un dossier de destination vierge est fortement conseillé
> pour la première utilisation.**
>
> Si la destination contient déjà des fichiers non organisés ou issus d'un
> autre outil, l'indexation initiale peut produire des résultats inattendus.
> Pour les passes suivantes, réutiliser le même dossier de destination est
> parfaitement sûr et recommandé.

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

### Options disponibles dans l'interface

| Option | Détail |
|---|---|
| **Déplacer les fichiers** | Déplace au lieu de copier ; supprime les dossiers vides après passage |
| **Supprimer les doublons exacts (SHA256)** | Supprime directement les doublons identiques bit pour bit, sans confirmation. Les doublons visuels et PDF restent déplacés vers `Doublon/` |
| **Seuil similarité visuelle** | De 0 (identique strict) à 10 (très permissif). Contrôle la tolérance du pHash pour les images |
| **Annuler** | Interrompt proprement le traitement en cours |

### Résumé affiché en fin de traitement

```
✅ Traités      : 1 842
🗑️  Supprimés    : 312
📋 Doublons     : 47
❌ Erreurs      : 0
```

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

- Détection visuelle (pHash) : images uniquement
- Détection PDF : ne fonctionne pas sur les PDFs entièrement scannés (sans texte extractible) — le SHA256 prend le relais
- Sur très gros volumes (> 100 000 fichiers), l'indexation initiale de la destination peut prendre quelques secondes supplémentaires

---

## 📜 Licence

MIT — libre d'utilisation et de modification

---

## 🤝 Contribution

Les contributions sont les bienvenues :

- Amélioration des performances sur gros volumes
- Support de nouveaux formats de métadonnées (vidéo, audio)
- Optimisation du seuil pHash adaptatif
