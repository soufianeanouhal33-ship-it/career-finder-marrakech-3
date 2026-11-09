# 🎯 Career Finder Marrakech (v6)

Application web pour trouver des **entreprises IA & IT à Marrakech**, consulter des **offres de stage/emploi**,
**envoyer son CV par e-mail** et **suivre ses candidatures**.

## Fonctionnalités

| Page | Contenu |
|---|---|
| 🏠 Accueil | Chiffres clés, meilleures opportunités, dernières offres |
| 🏢 Entreprises | Recherche, filtre par **secteur** (11 secteurs, détection automatique), score, e-mail, favoris ; envoi du CV, suivi, modification |
| 📄 Offres | Offres de stage/emploi, filtres par **type de stage** et **contrat**, ajout et import |
| 🗺️ Carte | Entreprises sur carte interactive (Folium/OpenStreetMap), filtrables par secteur et score |
| 📬 Candidatures | Kanban (À contacter → Envoyée → Entretien → Offre reçue / Refusée) |
| 📊 Statistiques | Graphiques : secteurs, types de stage, contrats, présence numérique, candidatures |
| 🎯 Profil & Matching | Compétences + recommandations d'entreprises (score indicatif) |
| ⚙️ Collecte & Import | Google Places, import Excel (entreprises), import Excel/CSV (offres), ajout manuel, exports |

**Sécurité** : comptes utilisateurs (mots de passe hachés scrypt), données (favoris, candidatures, profil) propres à chaque compte, premier compte = administrateur.

## Lancer l'application (Streamlit)

```bash
pip install -r requirements.txt
copy .env.example .env   # puis remplir SECRET_KEY (>32 caractères)
streamlit run streamlit_app.py
```

**Port 8501** : http://localhost:8501 — l'interface complète (8 pages, auth, envoi CV, carte Folium, graphiques) tourne sur le même moteur Python que le backend. La base `data/career_app.db` partagée est réutilisée.

### Version API classique (FastAPI + page statique)

```bash
uvicorn backend.main:app --reload   # port 8000
```

## Lancer l'application (FastAPI, sans Docker)

```bash
python -m venv venv
venv\Scripts\activate            # Windows   (Mac/Linux : source venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env           # Mac/Linux : cp .env.example .env
# édite .env : SECRET_KEY (obligatoire) et GOOGLE_MAPS_API_KEY
uvicorn backend.main:app --reload
```
Ouvre **http://localhost:8000** et crée ton compte (le premier devient administrateur).
Génère `SECRET_KEY` avec : `python -c "import secrets; print(secrets.token_urlsafe(48))"`.

### Avec Docker
```bash
cp .env.example .env             # puis remplis SECRET_KEY et GOOGLE_MAPS_API_KEY
docker compose up --build
```
Ouvre http://localhost:8000. La base SQLite est conservée dans le volume `career_data`.

## Envoi du CV par e-mail

1. Renseigne `SMTP_HOST`, `SMTP_FROM` (+ `SMTP_USER`, `SMTP_PASSWORD`) dans `.env`. Gmail : `smtp.gmail.com`, port 587, avec un **mot de passe d'application**.
2. Une entreprise doit avoir un **e-mail** (colonne `email` à l'import Excel, ou bouton ✏️).
3. Entreprises → **✉️ CV** : choisis ton PDF, relis le message, envoie.

Garde-fous : le destinataire vient toujours de la base, CV PDF de 5 Mo max, 10 envois/heure et 30/jour par utilisateur, confirmation avant de renvoyer à la même entreprise dans les 7 jours. Chaque envoi crée automatiquement une candidature « Envoyée ». Sans SMTP, le lien « Ouvrir dans ma messagerie » (mailto) reste disponible.

## Importer des données

- **Entreprises (Excel)** : colonnes `entreprise` (obligatoire), `type`, `secteur`, `adresse`, `lat`, `lon`, `note`, `site_web`, `telephone`, `email`, `statut_google`.
- **Offres (Excel ou CSV)** : colonne du titre obligatoire (`titre`, `intitulé` ou `poste`) ; reconnues aussi : `entreprise`/`société`, `contrat`, `type de stage`, `ville`, `date de publication`, `lien`, `description`. Les offres sont rattachées à l'entreprise du catalogue portant le même nom. Les doublons sont ignorés.

## Tests
```bash
pip install pytest httpx
pytest
```

## Structure
```
streamlit_app.py          # interface Streamlit complète (8 pages)
backend/   main.py (API FastAPI), database.py, security.py (auth), mailer.py (SMTP)
pipeline/  google_places.py, cleaner.py, excel_importer.py, sectors.py
frontend/static/   index.html, css/style.css, js/ (core, pages-a, pages-b, main)
tests/     test_auth.py, test_features.py
```

## Limites connues
- Les offres ne sont pas collectées automatiquement : elles viennent d'ajouts manuels ou d'imports de fichiers.
- Les e-mails d'entreprises ne sont pas fournis par Google Places : ils viennent des imports ou de la saisie.
- Le matching reste simple (mots-clés) : les résultats sont indicatifs.
- Sessions stockées dans le navigateur (Streamlit : session state) ; pas encore de réinitialisation de mot de passe.
- Pour un accès public, place l'application derrière un reverse proxy **HTTPS** (Caddy, Nginx, Traefik).
