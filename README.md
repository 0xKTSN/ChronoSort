# 📸 ChronoSort

> Outil Python pour trier, normaliser et dédupliquer automatiquement
> tous types de fichiers (photos, documents, etc.) avec priorité aux
> métadonnées réelles.

---

## 🚀 Objectif

ChronoSort permet de : - Aplatir une arborescence de dossiers\

- Renommer les fichiers avec une date fiable\
- Trier chronologiquement automatiquement\
- Détecter et isoler les doublons\
- Nettoyer les dossiers vides

---

## 🧠 Fonctionnement

1. 📅 Date :
   - EXIF (priorité)
   - fallback : date de modification

2. 🏷️ Nom : YYYY-MM-DD_HH-MM-SS_nom.ext

3. 🔍 Doublons :
   - SHA256 (exact)
   - pHash (images uniquement)

4. 📁 Organisation :
   - fichiers uniques → racine
   - doublons → /Doublon

---

## 📦 Installation

```bash
pip install Pillow imagehash tqdm
```

---

## ▶️ Utilisation

```bash
python main.py
```

---

## ⚠️ Limites

- Détection visuelle : images uniquement
- Hash peut être lent sur gros volumes

---

## 📜 Licence

MIT — libre d’utilisation et modification

---

## 🤝 Contribution

Les contributions sont les bienvenues :

- amélioration des performances
- nouveaux formats supportés
- optimisation du hash visuel
