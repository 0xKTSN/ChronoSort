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
- Détecter et isoler les doublons (exact + visuel + contenu PDF)
- Organiser les fichiers par catégorie dans la destination
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
   - Hash texte — doublon de contenu PDF (PDFs re-sauvegardés ou re-exportés)

4. **📁 Organisation automatique par catégorie :**

```
destination/
├── Images/
│   ├── JPG/
│   ├── PNG/
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
│   └── ...
├── Archives/
├── Autres/
└── Doublon/
```

> Les dossiers ne sont créés que si des fichiers correspondants sont présents.

5. **🔄 Indexation de la destination au démarrage :**

   À chaque lancement, ChronoSort commence par scanner les fichiers **déjà présents**
   dans le dossier de destination et les intègre dans les structures de déduplication.
   Cela signifie que **vous pouvez réutiliser le même dossier de destination à chaque
   passe**, même si le dossier source change — aucun doublon ne sera introduit entre
   deux sessions.

   Le journal affiche explicitement cette phase au démarrage :
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

> `pypdf` est requis pour la détection de doublons dans les PDFs.

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
