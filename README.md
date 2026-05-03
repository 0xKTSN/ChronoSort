# 📸 ChronoSort

> Outil Python pour trier, dédupliquer, organiser et renommer automatiquement
> tous types de fichiers avec priorité aux métadonnées réelles.

---

## 🚀 Vue d'ensemble

ChronoSort propose **trois modes** adaptés à des situations différentes :

| Mode | Cas d'usage | Destination requise |
|---|---|---|
| **✦ Mode Tri** | Dossier chaotique à organiser | ✅ Oui |
| **⟺ Mode Miroir** | Dossier organisé à répliquer | ✅ Oui |
| **✏ Mode Renommage** | Renommage libre sur place | ❌ Non |

---

## 🧠 Fonctionnement détaillé

### ✦ Mode Tri

Pour les dossiers sans organisation préalable. ChronoSort renomme, classe et déduplique.

**Étape 1 — Nettoyage et renommage**

Si un fichier a accumulé plusieurs préfixes date suite à des passes répétées
(ex. `2024-01-15_14-30-00_2023-12-01_photo.jpg`), le surplus est supprimé
automatiquement : seul le premier préfixe est conservé.

Si le fichier a déjà un préfixe date propre → conservé tel quel, jamais re-préfixé.

Sinon → date lue depuis les métadonnées EXIF (priorité) ou la date de modification.

Format final : `YYYY-MM-DD_HH-MM-SS_nom_original.ext`

**Étape 2 — Organisation par catégorie**

```
destination/
├── Images/
│   ├── JPG/        ├── PNG/        ├── HEIC/  ...
├── Vidéos/
│   ├── MP4/        ├── MKV/  ...
├── PDF/
├── Word/           ├── Excel/      ├── PowerPoint/
├── Audio/
│   ├── MP3/        ├── FLAC/  ...
├── Archives/
├── Autres/
└── Doublon/
    ├── Images/JPG/ ├── PDF/  ...     ← doublons classés par catégorie
```

> Les dossiers ne sont créés que si des fichiers correspondants sont présents.

**Étape 3 — Déduplication**

| Type | Méthode | Action |
|---|---|---|
| Fichiers identiques bit pour bit | SHA256 | Suppression directe |
| Images visuellement similaires | pHash via BK-tree | Déplacement vers `Doublon/` |
| PDFs au contenu identique | Hash du texte extrait | Déplacement vers `Doublon/` |

Les fichiers dans `Doublon/` sont classés par catégorie pour faciliter la vérification manuelle.
La suppression SHA256 est sans appel : deux fichiers avec le même SHA256 sont à 100 % identiques.

---

### ⟺ Mode Miroir

Pour les dossiers possédant une organisation structurelle à conserver lors d'une sauvegarde.

- Arborescence source reproduite à l'identique dans la destination
- Aucun renommage, aucun tri par catégorie
- Doublons exacts (SHA256) → suppression directe de la source
- Option : reproduction des dossiers vides (coché par défaut)

```
source/                       destination/
├── Administratif/            ├── Administratif/
│   ├── 2024/                 │   ├── 2024/
│   │   └── contrat.pdf  →    │   │   └── contrat.pdf
│   └── 2025/  (vide)    →    │   └── 2025/  (vide préservé)
└── Photos/                   └── Photos/
    └── photo.jpg        →        └── photo.jpg
```

> **Sécurité anti-perte de données** : avant de supprimer un fichier source, le script
> vérifie que le fichier référencé par ce hash existe encore en destination.
> Si le fichier a été supprimé manuellement (hash orphelin), la source est copiée
> normalement plutôt que supprimée.

---

### ✏ Mode Renommage

Pour renommer des fichiers selon un format entièrement personnalisable, sur place,
sans dossier destination. Parcourt récursivement tous les sous-dossiers.

**Tokens disponibles**

| Token | Remplacé par | Exemple |
|---|---|---|
| `{date}` | Date du fichier (EXIF ou modification) | `2024-01-15` |
| `{heure}` | Heure du fichier | `14-30-00` |
| `{nom}` | Nom original sans extension | `photo_vacances` |
| `{ext}` | Extension sans le point | `jpg` |
| `{compteur}` | Numéro séquentiel par dossier | `0001` |
| `{dossier}` | Nom du dossier parent direct | `Vacances` |

> Si `{ext}` est absent du format, l'extension originale est conservée automatiquement.

**Exemples de formats**

```
{date}_{heure}_{nom}           →  2024-01-15_14-30-00_photo.jpg
{dossier}_{compteur}_{nom}     →  Vacances_0001_photo.jpg
{compteur}_{date}              →  0001_2024-01-15.jpg
Backup_{date}_{nom}            →  Backup_2024-01-15_photo.jpg
```

**Compteur**
- Repart à `0001` pour chaque sous-dossier (indépendant par dossier)
- Padding automatique selon le nombre de fichiers (minimum 4 chiffres)
- Ordre configurable : `0001 = plus ancien` (croissant) ou `0001 = plus récent` (décroissant)

**Aperçu en direct**
L'interface affiche un tableau Avant → Après sur 5 fichiers représentatifs,
mis à jour automatiquement 400 ms après chaque modification du format.

**Gestion des conflits**

| Situation | Action |
|---|---|
| Nouveau nom déjà correct | Ignoré (aucune opération) |
| Deux fichiers → même nouveau nom, contenu identique (SHA256) | Suppression du doublon |
| Deux fichiers → même nouveau nom, contenu différent | Suffixe `_1`, `_2`… |
| Conflit circulaire (a → b et b → a) | Résolu via renommage en deux phases (temp UUID) |

---

### ⚡ Index persistant (Mode Tri et Miroir)

À la fin de chaque traitement, ChronoSort sauvegarde un index dans la destination :

```
destination/.chronosort_index.json
```

Invisible dans l'explorateur Windows. Il stocke les hashes SHA256, pHash et PDF
de tous les fichiers traités. Lors de la passe suivante, l'index est rechargé
directement — aucun fichier relu, indexation instantanée.

```
# Premier lancement :
🔍 Indexation de la destination : 2 000 fichier(s)…
✅ Indexation terminée.
💾 Index mis à jour → .chronosort_index.json

# Passes suivantes :
⚡ Index chargé (2 000 fichier(s), mis à jour le 2026-05-03T14:22:10)
   Indexation instantanée — aucun fichier relu.
```

| Situation | Comportement |
|---|---|
| Index absent | Scan complet + création |
| Index présent, même mode | Chargement instantané |
| Index présent, mode différent | Avertissement + scan complet |
| Index corrompu | Avertissement + scan complet |
| Passe annulée | Index sauvegardé partiellement |

Poids : ~80 octets/fichier. 10 000 fichiers → ~800 Ko.

> Utilisez **"Réinitialiser l'index"** si vous avez supprimé manuellement des fichiers
> de la destination entre deux passes.

---

## ⚠️ Recommandations

- **Mode Tri / Miroir** : commencer avec un dossier de destination vierge pour la première utilisation.
- **Mode Renommage** : tester l'aperçu avant de lancer, surtout sur un grand nombre de fichiers.
- L'option "Déplacer les fichiers" est irréversible — préférer "Copier" pour un premier essai.

---

## 📦 Installation

Nécessite **Python 3.10+**.

```bash
pip install -r requirements.txt
```

---

## ▶️ Utilisation

```bash
python main.py
```

### Options de l'interface

| Option | Mode(s) | Détail |
|---|---|---|
| **Déplacer les fichiers** | Tri · Miroir | Déplace au lieu de copier ; supprime les dossiers vides source après passage |
| **Seuil similarité visuelle** | Tri | De 0 (identique strict) à 10 (très permissif). Contrôle la tolérance pHash |
| **Reproduire les dossiers vides** | Miroir | Recrée les dossiers vides de la source dans la destination. Coché par défaut |
| **Format de renommage** | Renommage | Chaîne libre avec tokens. Aperçu en direct |
| **Ordre du compteur** | Renommage | Croissant (0001 = plus ancien) ou décroissant (0001 = plus récent) |
| **Réinitialiser l'index** | Tri · Miroir | Supprime l'index JSON pour forcer un scan complet |

### Résumés de fin de traitement

**Mode Tri**
```
  ✅  Triés      : 1 842    →  fichiers placés en destination
  🗑️   Supprimés  : 312      →  doublons SHA256 exacts supprimés
  📋  Doublon/   : 47       →  doublons pHash/PDF déplacés vers Doublon/
  ❌  Erreurs    : 0
```

**Mode Miroir**
```
  ✅  Copiés     : 1 842
  🗑️   Supprimés  : 312
  ❌  Erreurs    : 0
```

**Mode Renommage**
```
  ✏️   Renommés   : 134
  🗑️   Supprimés  : 12      →  doublons exacts après renommage
  ⏭️   Ignorés    : 1 696   →  noms déjà corrects
  ❌  Erreurs    : 0
```

---

## 🪟 Générer un exécutable Windows (.exe)

### Commande

```bash
python -m PyInstaller --onefile --windowed --name "ChronoSort" --icon="icon.ico" main.py
```

> Retirer `--icon="icon.ico"` si aucune icône n'est disponible.

Le fichier `ChronoSort.exe` se trouve dans `dist/` après la compilation.

| Point | Détail |
|---|---|
| Taille | ~30–60 Mo |
| Premier lancement | 3–5 s (décompression temp) — normal |
| Antivirus | Faux positif Windows Defender possible — autoriser manuellement |
| Portabilité | `.exe` Windows uniquement |

Dossiers PyInstaller supprimables après compilation :
```
build/   dist/   ChronoSort.spec
```

---

## ⚠️ Limites

- Détection pHash : images uniquement (Mode Tri)
- Détection PDF : PDFs scannés non pris en charge (fallback SHA256)
- Mode Renommage : si interrompu en phase 1 du renommage deux phases, des fichiers `__cst_xxxxx` peuvent rester — les renommer manuellement ou relancer le mode sur le même dossier
- Hashes orphelins en cas de suppression manuelle → "Réinitialiser l'index"

---

## 📜 Licence

MIT — libre d'utilisation et de modification

---

## 🤝 Contribution

- Support de nouveaux formats de métadonnées (vidéo, audio)
- Amélioration des performances sur très gros volumes
- Optimisation du seuil pHash adaptatif
