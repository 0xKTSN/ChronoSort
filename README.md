# 📸 ChronoSort

> Outil Python pour trier, normaliser et dédupliquer automatiquement
> tous types de fichiers (photos, documents, etc.) avec priorité aux
> métadonnées réelles.

---

## 🚀 Objectif

ChronoSort propose deux modes distincts pour gérer vos fichiers :

- **Mode Tri** — renomme, classe par catégorie, déduplique via SHA256 + pHash + contenu PDF
- **Mode Miroir** — reproduit l'arborescence source, déduplique uniquement via SHA256

Dans les deux cas : indexation de la destination au démarrage, progression en temps réel, annulation possible.

---

## 🧠 Fonctionnement

### ✦ Mode Tri

Conçu pour organiser un dossier chaotique de fichiers en une bibliothèque propre et structurée.

**1. Renommage par date**
- EXIF via `getexif()` (priorité pour les photos)
- Fallback : date de modification du fichier
- Format : `YYYY-MM-DD_HH-MM-SS_nom_original.ext`

**2. Organisation automatique par catégorie**

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

**3. Déduplication**

| Méthode | Scope | Action par défaut | Si option activée |
|---|---|---|---|
| SHA256 | Tous fichiers | Déplacement vers `Doublon/` | **Suppression directe** |
| pHash | Images uniquement | Déplacement vers `Doublon/` | Déplacement vers `Doublon/` |
| Hash texte | PDFs uniquement | Déplacement vers `Doublon/` | Déplacement vers `Doublon/` |

> Les doublons visuels (pHash) et PDF ne sont **jamais supprimés automatiquement**,
> même si l'option SHA256 est activée — ils restent dans `Doublon/` pour vérification.

---

### ⟺ Mode Miroir

Conçu pour dédupliquer et sauvegarder un dossier en conservant son organisation d'origine.

- L'arborescence source est reproduite à l'identique dans la destination
- Aucun renommage des fichiers
- Aucun tri par catégorie
- Seul le SHA256 est utilisé — doublon exact = **suppression directe**, sans dossier `Doublon/`

```
source/                      destination/
├── Vacances/                ├── Vacances/
│   ├── 2023/                │   ├── 2023/
│   │   ├── photo1.jpg  →    │   │   ├── photo1.jpg
│   │   └── photo1_copie ✕   │   │   (supprimé — SHA256 identique)
│   └── photo2.jpg      →    │   └── photo2.jpg
└── Documents/               └── Documents/
    └── rapport.pdf     →        └── rapport.pdf
```

---

### 🔄 Indexation de la destination au démarrage

À chaque lancement, ChronoSort scanne les fichiers **déjà présents** dans la destination
et les intègre dans les structures de déduplication avant de traiter la source.

Cela signifie que vous pouvez **réutiliser le même dossier de destination à chaque passe**,
même si le dossier source change — aucun doublon ne sera introduit entre deux sessions.

```
🔍 Indexation de la destination : 2 000 fichier(s) déjà présent(s)…
   (Les doublons seront détectés même si le dossier source change.)
✅ Indexation terminée — 2 000 fichier(s) référencé(s).
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

| Option | Mode | Détail |
|---|---|---|
| **Déplacer les fichiers** | Les deux | Déplace au lieu de copier ; supprime les dossiers vides source après passage |
| **Supprimer les doublons exacts (SHA256)** | Tri uniquement | Supprime directement les doublons identiques bit pour bit, sans confirmation |
| **Seuil similarité visuelle** | Tri uniquement | De 0 (identique strict) à 10 (très permissif). Contrôle la tolérance du pHash |

### Résumé affiché en fin de traitement

```
────────────────────────────────────────────────────
  ✅  Traités    : 1 842
  🗑️   Supprimés  : 312
  📋  Doublons   : 47
  ❌  Erreurs    : 0
────────────────────────────────────────────────────
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

- Détection visuelle (pHash) : images uniquement, Mode Tri uniquement
- Détection PDF : ne fonctionne pas sur les PDFs entièrement scannés — le SHA256 prend le relais
- Sur très gros volumes (> 100 000 fichiers), l'indexation initiale peut prendre quelques secondes supplémentaires

---

## 📜 Licence

MIT — libre d'utilisation et de modification

---

## 🤝 Contribution

Les contributions sont les bienvenues :

- Amélioration des performances sur gros volumes
- Support de nouveaux formats de métadonnées (vidéo, audio)
- Optimisation du seuil pHash adaptatif
