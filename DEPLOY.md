# 🚀 Déploiement public — Career Finder Marrakech (Streamlit)

## Deploy rapide (5 minutes, 100% gratuit)

### 1. Poussi ton code sur GitHub (si pas encore fait)

```bash
# Remplace TON-PSEUDO et NOM-DU-DEPOT par tes vraies valeurs
git remote set-url origin https://github.com/TON-PSEUDO/NOM-DU-DEPOT.git
git push origin main
```

### 2. Déployer sur Streamlit Cloud (gratuit)

1. Va sur https://share.streamlit.io (ou https://streamlit.io/cloud)
2. **New app** → choisis ton dépôt GitHub
3. **Main file** : `streamlit_app.py`
4. **Python version** : 3.12 (ou 3.11)
5. Cliquez **Deploy** — l'app arrive en 1-2 minutes à l'adresse `https://NOM-DU-DEPOT.streamlit.app`

### 3. Mettre les secrets (OBLIGATOIRE)

Dans Streamlit Cloud : **App Settings → Secrets** → colle :

```toml
SECRET_KEY = "test-secret-key-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"  # >32 car., génère : python -c "import secrets; print(secrets.token_urlsafe(48))"
GOOGLE_MAPS_API_KEY = ""
ALLOW_REGISTRATION = "true"
SMTP_HOST = ""
SMTP_PORT = 587
SMTP_SECURITY = "starttls"
SMTP_USER = ""
SMTP_PASSWORD = ""
SMTP_FROM = ""
SMTP_FROM_NAME = "Career Finder"
```

Clique **Save**, puis **Reboot app**.

> Sans `SECRET_KEY` valide, les sessions seront invalidées à chaque redémarrage.

### 4. Accès public

- Ton lien est maintenant **public** : `https://NOM-DU-DEPOT.streamlit.app`
- N'importe qui peut ouvrir, créer un compte, et utiliser l'app
- Base SQLite **éphémère** sur Streamlit Cloud : les données sont perdues si l'app dort ou se redémarre (limite du plan gratuit). Pour une base persistante : Turso, Neon, ou Hugging Face Spaces.

---

## Version locale (avant deploy)

```bash
pip install -r requirements.txt
copy .env.example .env   # puis remplir SECRET_KEY
streamlit run streamlit_app.py   # http://localhost:8501
```

## Alternatives gratuites

| Option | URL modèle | Base persistante ? |
|---|---|---|
| **Streamlit Cloud** (recommandé) | `*.streamlit.app` | Non (gratuit) |
| Hugging Face Spaces | `*.hf.space` | Possible (SQLite volume) |
| Render (free tier) | `*.onrender.com` | Éphémère aussi |

## Dépannage

- **App not found** : vérifie que `streamlit_app.py` est à la racine du dépôt
- **ImportError** : les dépendances sont dans `requirements.txt` (déjà mis à jour avec streamlit, folium, etc.)
- **Données perdues** : normal sur Streamlit Cloud gratuit — utilise un fichier Excel pour sauvegarder/ exporter tes données (page Collecte & Import → Exports)
