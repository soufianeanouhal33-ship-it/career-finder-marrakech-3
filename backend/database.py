import sqlite3
from pathlib import Path

import pandas as pd

from pipeline.sectors import classify_sector

DB_DIR = Path(__file__).resolve().parent.parent / "data"
DB_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DB_DIR / "career_app.db"


def get_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_columns(conn, table: str, columns: dict) -> list:
    """Ajoute les colonnes manquantes à une table existante (migration légère
    pour les bases créées par une version antérieure de l'app)."""
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    existing = {row[1] for row in cur.fetchall()}
    added = []
    for name, ddl_type in columns.items():
        if name not in existing:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl_type}")
            added.append(name)
    conn.commit()
    return added


def init_db():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS opportunities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            place_id TEXT UNIQUE,
            nom TEXT,
            adresse TEXT,
            note REAL,
            latitude REAL,
            longitude REAL,
            score_opportunite INTEGER,
            mots_cles TEXT,
            source TEXT DEFAULT 'Google Places',
            favori INTEGER DEFAULT 0,
            site_web TEXT DEFAULT '',
            telephone TEXT DEFAULT '',
            google_maps_url TEXT DEFAULT '',
            date_ajout TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    added_cols = _ensure_columns(conn, "opportunities", {
        "site_web": "TEXT DEFAULT ''",
        "telephone": "TEXT DEFAULT ''",
        "google_maps_url": "TEXT DEFAULT ''",
        "added_by": "TEXT DEFAULT ''",
        "secteur": "TEXT DEFAULT 'Autre'",
        "email": "TEXT DEFAULT ''",
    })
    if "secteur" in added_cols:
        # Base créée par une version antérieure : classer les entreprises existantes
        for row in cur.execute("SELECT id, nom, mots_cles FROM opportunities").fetchall():
            cur.execute("UPDATE opportunities SET secteur=? WHERE id=?",
                        (classify_sector(row["nom"], row["mots_cles"]), row["id"]))
        conn.commit()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            is_admin INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS favorites (
            user TEXT NOT NULL,
            opportunity_id INTEGER NOT NULL,
            PRIMARY KEY (user, opportunity_id),
            FOREIGN KEY (opportunity_id) REFERENCES opportunities(id) ON DELETE CASCADE
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user TEXT,
            company TEXT,
            poste TEXT,
            statut TEXT DEFAULT 'À contacter',
            date_candidature TEXT,
            remarque TEXT,
            opportunity_id INTEGER,
            date_ajout TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (opportunity_id) REFERENCES opportunities(id)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_applications_user ON applications(user)")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS profile (
            user TEXT PRIMARY KEY,
            skills TEXT DEFAULT '',
            experience_years REAL DEFAULT 0,
            bio TEXT DEFAULT '',
            cv_filename TEXT DEFAULT '',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS offers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titre TEXT NOT NULL,
            entreprise TEXT DEFAULT '',
            opportunity_id INTEGER,
            contrat TEXT DEFAULT 'Stage',
            type_stage TEXT DEFAULT 'Non renseigné',
            ville TEXT DEFAULT 'Marrakech',
            date_publication TEXT DEFAULT '',
            url TEXT DEFAULT '',
            description TEXT DEFAULT '',
            source TEXT DEFAULT 'Ajout manuel',
            added_by TEXT DEFAULT '',
            date_ajout TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (opportunity_id) REFERENCES opportunities(id)
        )
    """)
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_offers_unique ON offers(titre, entreprise, date_publication)")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS email_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user TEXT NOT NULL,
            opportunity_id INTEGER,
            to_email TEXT NOT NULL,
            subject TEXT,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_email_log_user ON email_log(user, sent_at)")
    conn.commit()
    conn.close()


def upsert_opportunities(df: pd.DataFrame, added_by: str = "") -> int:
    """Insère les nouvelles opportunités, met à jour celles déjà connues (par place_id)."""
    if df.empty:
        return 0
    conn = get_connection()
    cur = conn.cursor()
    count = 0
    for _, row in df.iterrows():
        cur.execute("""
            INSERT INTO opportunities
                (place_id, nom, adresse, note, latitude, longitude, score_opportunite,
                 mots_cles, source, site_web, telephone, google_maps_url, added_by, secteur, email)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(place_id) DO UPDATE SET
                nom=excluded.nom,
                adresse=excluded.adresse,
                note=excluded.note,
                latitude=excluded.latitude,
                longitude=excluded.longitude,
                score_opportunite=excluded.score_opportunite,
                mots_cles=excluded.mots_cles,
                site_web=excluded.site_web,
                telephone=excluded.telephone,
                google_maps_url=excluded.google_maps_url,
                secteur=CASE WHEN opportunities.secteur IN ('', 'Autre') THEN excluded.secteur
                             ELSE opportunities.secteur END,
                email=CASE WHEN excluded.email != '' THEN excluded.email ELSE opportunities.email END
        """, (
            row.get("place_id"), row.get("nom"), row.get("adresse"), row.get("note"),
            row.get("latitude"), row.get("longitude"), row.get("score_opportunite"),
            row.get("mots_cles", ""), row.get("source", "Google Places"),
            row.get("site_web", "") or "", row.get("telephone", "") or "",
            row.get("google_maps_url", "") or "", added_by,
            (row.get("secteur") or classify_sector(row.get("nom"), row.get("mots_cles"))),
            (row.get("email", "") or ""),
        ))
        count += 1
    conn.commit()
    conn.close()
    return count


def toggle_favorite(user: str, opportunity_id: int) -> bool:
    """Bascule le favori de CET utilisateur (les favoris ne sont plus partagés)."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM opportunities WHERE id=?", (opportunity_id,))
    if cur.fetchone() is None:
        conn.close()
        raise ValueError("Opportunité introuvable")
    cur.execute("SELECT 1 FROM favorites WHERE user=? AND opportunity_id=?", (user, opportunity_id))
    if cur.fetchone():
        cur.execute("DELETE FROM favorites WHERE user=? AND opportunity_id=?", (user, opportunity_id))
        is_fav = False
    else:
        cur.execute("INSERT INTO favorites (user, opportunity_id) VALUES (?, ?)", (user, opportunity_id))
        is_fav = True
    conn.commit()
    conn.close()
    return is_fav


def get_opportunity_owner(opportunity_id: int):
    """Retourne (existe, added_by)."""
    conn = get_connection()
    row = conn.execute("SELECT added_by FROM opportunities WHERE id=?", (opportunity_id,)).fetchone()
    conn.close()
    return (row is not None), (row["added_by"] if row else "")


def delete_opportunity(opportunity_id: int) -> None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM favorites WHERE opportunity_id=?", (opportunity_id,))
    cur.execute("DELETE FROM opportunities WHERE id=?", (opportunity_id,))
    conn.commit()
    conn.close()


def get_opportunities_for_user(user: str, min_score: int = 0, favoris_only: bool = False) -> pd.DataFrame:
    """Opportunités (catalogue partagé) avec la colonne `favori` propre à l'utilisateur."""
    conn = get_connection()
    sql = """
        SELECT o.id, o.place_id, o.nom, o.adresse, o.note, o.latitude, o.longitude,
               o.score_opportunite, o.mots_cles, o.source, o.site_web, o.telephone,
               o.google_maps_url, o.added_by, o.date_ajout, o.secteur, o.email,
               CASE WHEN f.user IS NULL THEN 0 ELSE 1 END AS favori,
               (SELECT MAX(sent_at) FROM email_log e
                 WHERE e.user = ? AND e.opportunity_id = o.id) AS cv_envoye_le
        FROM opportunities o
        LEFT JOIN favorites f ON f.opportunity_id = o.id AND f.user = ?
        WHERE o.score_opportunite >= ?
    """
    params = [user, user, min_score]
    if favoris_only:
        sql += " AND f.user IS NOT NULL"
    sql += " ORDER BY o.score_opportunite DESC"
    df = pd.read_sql_query(sql, conn, params=params)
    conn.close()
    return df


# ---------- Utilisateurs ----------

def count_users() -> int:
    conn = get_connection()
    n = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    conn.close()
    return n


def get_user(username: str):
    conn = get_connection()
    row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    conn.close()
    return dict(row) if row else None


def create_user(username: str, password_hash: str) -> dict:
    """Crée un utilisateur. Le tout premier compte est administrateur et récupère
    les données héritées de l'ancienne version sans authentification (`demo_user`).
    Lève ValueError si le nom est déjà pris."""
    conn = get_connection()
    cur = conn.cursor()
    is_admin = 1 if cur.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0 else 0
    try:
        cur.execute(
            "INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, ?)",
            (username, password_hash, is_admin),
        )
    except sqlite3.IntegrityError:
        conn.close()
        raise ValueError("Ce nom d'utilisateur existe déjà")
    if is_admin:
        cur.execute("UPDATE applications SET user=? WHERE user='demo_user'", (username,))
        cur.execute("UPDATE profile SET user=? WHERE user='demo_user'", (username,))
        cur.execute("UPDATE opportunities SET added_by=? WHERE added_by='' OR added_by IS NULL", (username,))
        cur.execute(
            "INSERT OR IGNORE INTO favorites (user, opportunity_id) "
            "SELECT ?, id FROM opportunities WHERE favori=1", (username,),
        )
    conn.commit()
    conn.close()
    return {"username": username, "is_admin": bool(is_admin)}


# ---------- Candidatures (par utilisateur) ----------

def application_owner(application_id: int):
    conn = get_connection()
    row = conn.execute("SELECT user FROM applications WHERE id=?", (application_id,)).fetchone()
    conn.close()
    return row["user"] if row else None


def get_profile(user: str = "demo_user") -> dict:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM profile WHERE user=?", (user,))
    row = cur.fetchone()
    conn.close()
    if row is None:
        return {"user": user, "skills": "", "experience_years": 0.0, "bio": "", "cv_filename": ""}
    return dict(row)


def upsert_profile(data: dict) -> None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO profile (user, skills, experience_years, bio, cv_filename)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user) DO UPDATE SET
            skills=excluded.skills,
            experience_years=excluded.experience_years,
            bio=excluded.bio,
            cv_filename=excluded.cv_filename,
            updated_at=CURRENT_TIMESTAMP
    """, (
        data.get("user", "demo_user"), data.get("skills", ""),
        data.get("experience_years", 0.0), data.get("bio", ""),
        data.get("cv_filename", ""),
    ))
    conn.commit()
    conn.close()


def insert_manual_opportunity(data: dict, added_by: str = "") -> int:
    """Ajoute une entreprise saisie à la main. Lève ValueError si elle existe déjà."""
    conn = get_connection()
    cur = conn.cursor()
    place_id = data.get("place_id") or f"manual-{data.get('nom','')}-{data.get('adresse','')}"
    try:
        cur.execute(
            """
            INSERT INTO opportunities
                (place_id, nom, adresse, note, latitude, longitude, score_opportunite,
                 mots_cles, source, site_web, telephone, google_maps_url, added_by, secteur, email)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                place_id, data.get("nom"), data.get("adresse"), data.get("note", 0.0),
                data.get("latitude"), data.get("longitude"), data.get("score_opportunite", 0),
                data.get("mots_cles", ""), "Ajout manuel",
                data.get("site_web", "") or "", data.get("telephone", "") or "",
                data.get("google_maps_url", "") or "", added_by,
                data.get("secteur") or classify_sector(data.get("nom"), data.get("mots_cles")),
                data.get("email", "") or "",
            ),
        )
        conn.commit()
        new_id = cur.lastrowid
    except sqlite3.IntegrityError:
        raise ValueError("Cette entreprise existe déjà")
    finally:
        conn.close()
    return new_id


_EDITABLE_OPPORTUNITY_FIELDS = ("email", "telephone", "site_web", "secteur", "adresse")


def update_opportunity_fields(opportunity_id: int, fields: dict) -> None:
    cols = [k for k in fields if k in _EDITABLE_OPPORTUNITY_FIELDS]
    if not cols:
        raise ValueError("Aucun champ modifiable fourni")
    conn = get_connection()
    conn.execute(
        f"UPDATE opportunities SET {', '.join(c + '=?' for c in cols)} WHERE id=?",
        [fields[c] for c in cols] + [opportunity_id],
    )
    conn.commit()
    conn.close()


def get_opportunity(opportunity_id: int):
    conn = get_connection()
    row = conn.execute("SELECT * FROM opportunities WHERE id=?", (opportunity_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


# ---------- Offres de stage / d'emploi ----------

CONTRATS = ["Stage", "CDI", "CDD", "Premier Emploi", "Autre"]
TYPES_STAGE = ["Stage fonctionnel", "Stage de fin d'études", "Stage Pré-embauche", "Non renseigné"]

_OFFER_COLUMNS = ["titre", "entreprise", "opportunity_id", "contrat", "type_stage", "ville",
                  "date_publication", "url", "description", "source"]


def _offer_values(data: dict, added_by: str) -> list:
    contrat = data.get("contrat") or "Stage"
    type_stage = data.get("type_stage") or "Non renseigné"
    return [
        str(data.get("titre") or "").strip(),
        str(data.get("entreprise") or "").strip(),
        data.get("opportunity_id"),
        contrat if contrat in CONTRATS else "Autre",
        type_stage if type_stage in TYPES_STAGE else "Non renseigné",
        str(data.get("ville") or "Marrakech").strip(),
        str(data.get("date_publication") or "").strip(),
        str(data.get("url") or "").strip(),
        str(data.get("description") or "").strip(),
        str(data.get("source") or "Ajout manuel").strip(),
        added_by,
    ]


def insert_offer(data: dict, added_by: str = "") -> int:
    """Ajoute une offre. Lève ValueError si le titre est vide ou si l'offre existe déjà."""
    values = _offer_values(data, added_by)
    if not values[0]:
        raise ValueError("Le titre de l'offre est obligatoire")
    conn = get_connection()
    try:
        cur = conn.execute(
            f"INSERT INTO offers ({', '.join(_OFFER_COLUMNS)}, added_by) VALUES ({', '.join('?' * 11)})",
            values,
        )
        conn.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError:
        raise ValueError("Cette offre existe déjà")
    finally:
        conn.close()


def upsert_offers(rows: list, added_by: str = "") -> dict:
    """Insère une liste d'offres (dicts), ignore les doublons. Retourne {ajoutees, ignorees}."""
    added = skipped = 0
    for data in rows:
        try:
            insert_offer(data, added_by)
            added += 1
        except ValueError:
            skipped += 1
    return {"ajoutees": added, "ignorees": skipped}


def list_offers(q: str = "", contrat: str = "", type_stage: str = "", opportunity_id=None) -> pd.DataFrame:
    sql = """
        SELECT f.*, o.secteur AS secteur, o.email AS email_entreprise
        FROM offers f LEFT JOIN opportunities o ON o.id = f.opportunity_id
        WHERE 1=1
    """
    params = []
    if q:
        sql += " AND (f.titre LIKE ? OR f.entreprise LIKE ? OR f.description LIKE ?)"
        params += [f"%{q}%"] * 3
    if contrat:
        sql += " AND f.contrat = ?"
        params.append(contrat)
    if type_stage:
        sql += " AND f.type_stage = ?"
        params.append(type_stage)
    if opportunity_id is not None:
        sql += " AND f.opportunity_id = ?"
        params.append(opportunity_id)
    sql += " ORDER BY f.date_publication DESC, f.id DESC"
    conn = get_connection()
    df = pd.read_sql_query(sql, conn, params=params)
    conn.close()
    return df


def get_offer_owner(offer_id: int):
    conn = get_connection()
    row = conn.execute("SELECT added_by FROM offers WHERE id=?", (offer_id,)).fetchone()
    conn.close()
    return (row is not None), (row["added_by"] if row else "")


def delete_offer(offer_id: int) -> None:
    conn = get_connection()
    conn.execute("DELETE FROM offers WHERE id=?", (offer_id,))
    conn.commit()
    conn.close()


# ---------- Journal des e-mails envoyés ----------

def log_email(user: str, opportunity_id, to_email: str, subject: str) -> None:
    conn = get_connection()
    conn.execute(
        "INSERT INTO email_log (user, opportunity_id, to_email, subject) VALUES (?, ?, ?, ?)",
        (user, opportunity_id, to_email, subject),
    )
    conn.commit()
    conn.close()


def count_emails_since(user: str, hours: float) -> int:
    conn = get_connection()
    n = conn.execute(
        "SELECT COUNT(*) FROM email_log WHERE user=? AND sent_at >= datetime('now', ?)",
        (user, f"-{hours} hours"),
    ).fetchone()[0]
    conn.close()
    return n


def last_email_to(user: str, opportunity_id: int):
    """Date (UTC, 'YYYY-MM-DD HH:MM:SS') du dernier CV envoyé par cet utilisateur à cette entreprise."""
    conn = get_connection()
    row = conn.execute(
        "SELECT MAX(sent_at) AS d FROM email_log WHERE user=? AND opportunity_id=?",
        (user, opportunity_id),
    ).fetchone()
    conn.close()
    return row["d"] if row else None
