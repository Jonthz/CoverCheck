from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parents[1] / "app.db"


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS insurance_companies (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS insurance_plans (
    id INTEGER PRIMARY KEY,
    company_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    annual_deductible_cents INTEGER NOT NULL,
    coinsurance_percent INTEGER NOT NULL,
    max_coverage_cents INTEGER NOT NULL,
    FOREIGN KEY (company_id) REFERENCES insurance_companies(id)
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    full_name TEXT NOT NULL,
    age INTEGER NOT NULL,
    city TEXT NOT NULL,
    insurance_plan_id INTEGER NOT NULL,
    FOREIGN KEY (insurance_plan_id) REFERENCES insurance_plans(id)
);

CREATE TABLE IF NOT EXISTS specialties (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL,
    keywords TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS hospitals (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    city TEXT NOT NULL,
    network_tier TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS hospital_specialty_prices (
    hospital_id INTEGER NOT NULL,
    specialty_id INTEGER NOT NULL,
    list_price_cents INTEGER NOT NULL,
    PRIMARY KEY (hospital_id, specialty_id),
    FOREIGN KEY (hospital_id) REFERENCES hospitals(id),
    FOREIGN KEY (specialty_id) REFERENCES specialties(id)
);

CREATE TABLE IF NOT EXISTS insurance_contracts (
    id INTEGER PRIMARY KEY,
    plan_id INTEGER NOT NULL,
    hospital_id INTEGER NOT NULL,
    specialty_id INTEGER NOT NULL,
    negotiated_price_cents INTEGER NOT NULL,
    fixed_copay_cents INTEGER,
    coverage_percent INTEGER NOT NULL,
    in_network INTEGER NOT NULL,
    FOREIGN KEY (plan_id) REFERENCES insurance_plans(id),
    FOREIGN KEY (hospital_id) REFERENCES hospitals(id),
    FOREIGN KEY (specialty_id) REFERENCES specialties(id)
);

CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    thread_id TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    metadata_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript(SCHEMA)
        if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            seed_db(conn)


def seed_db(conn: sqlite3.Connection) -> None:
    conn.executemany(
        "INSERT INTO insurance_companies (id, name) VALUES (?, ?)",
        [(1, "SaludTotal"), (2, "AndesCare")],
    )
    conn.executemany(
        """
        INSERT INTO insurance_plans
        (id, company_id, name, annual_deductible_cents, coinsurance_percent, max_coverage_cents)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (1, 1, "SaludTotal Preferente", 10000, 10, 500000),
            (2, 1, "SaludTotal Basico", 25000, 25, 250000),
            (3, 2, "AndesCare Premium", 5000, 5, 800000),
        ],
    )
    conn.executemany(
        "INSERT INTO users (id, full_name, age, city, insurance_plan_id) VALUES (?, ?, ?, ?, ?)",
        [
            (1, "Ana Perez", 34, "Quito", 1),
            (2, "Carlos Rivas", 47, "Quito", 2),
            (3, "Mia Torres", 8, "Guayaquil", 3),
        ],
    )
    specialties = [
        (1, "Cardiologia", "Dolor de pecho, palpitaciones, presion alta.", "pecho,corazon,palpitaciones,presion,aire"),
        (2, "Pediatria", "Atencion medica para ninos y adolescentes.", "nino,nina,bebe,fiebre infantil,pediatria"),
        (3, "Dermatologia", "Piel, alergias, ronchas, acne, erupciones.", "piel,ronchas,acne,erupcion,alergia,manchas"),
        (4, "Traumatologia", "Golpes, fracturas, lesiones musculares o articulares.", "fractura,golpe,rodilla,hombro,dolor muscular,torcedura"),
        (5, "Medicina Interna", "Sintomas generales en adultos.", "fiebre,dolor cabeza,gripe,cansancio,malestar,tos"),
        (6, "Emergencia", "Sintomas potencialmente urgentes.", "desmayo,sangrado fuerte,dificultad respirar,dolor intenso,accidente"),
    ]
    conn.executemany(
        "INSERT INTO specialties (id, name, description, keywords) VALUES (?, ?, ?, ?)",
        specialties,
    )
    conn.executemany(
        "INSERT INTO hospitals (id, name, city, network_tier) VALUES (?, ?, ?, ?)",
        [
            (1, "Hospital Metropolitano", "Quito", "premium"),
            (2, "Clinica Norte", "Quito", "standard"),
            (3, "Hospital del Valle", "Quito", "standard"),
            (4, "Clinica Pacifico", "Guayaquil", "standard"),
        ],
    )
    prices = []
    base_prices = {
        1: [12000, 9500, 11000, 10500],
        2: [8000, 6500, 7200, 7000],
        3: [9000, 7000, 8500, 7600],
        4: [10000, 7800, 9000, 8300],
        5: [7500, 5800, 6900, 6200],
        6: [18000, 15000, 16500, 15500],
    }
    for specialty_id, amounts in base_prices.items():
        for hospital_id, amount in enumerate(amounts, start=1):
            prices.append((hospital_id, specialty_id, amount))
    conn.executemany(
        "INSERT INTO hospital_specialty_prices (hospital_id, specialty_id, list_price_cents) VALUES (?, ?, ?)",
        prices,
    )

    contracts = []
    contract_id = 1
    for plan_id in (1, 2, 3):
        for hospital_id, tier_factor in ((1, 90), (2, 78), (3, 82), (4, 80)):
            for specialty_id, amounts in base_prices.items():
                list_price = amounts[hospital_id - 1]
                negotiated = list_price * tier_factor // 100
                if plan_id == 1:
                    copay = 2500 if specialty_id != 6 else 5000
                    coverage = 80
                    in_network = hospital_id in (1, 2, 3)
                elif plan_id == 2:
                    copay = 4000 if specialty_id != 6 else 7000
                    coverage = 65
                    in_network = hospital_id in (2, 3, 4)
                else:
                    copay = 1500 if specialty_id != 6 else 3500
                    coverage = 90
                    in_network = hospital_id in (1, 3, 4)
                contracts.append((contract_id, plan_id, hospital_id, specialty_id, negotiated, copay, coverage, int(in_network)))
                contract_id += 1
    conn.executemany(
        """
        INSERT INTO insurance_contracts
        (id, plan_id, hospital_id, specialty_id, negotiated_price_cents, fixed_copay_cents, coverage_percent, in_network)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        contracts,
    )


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def get_users() -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT u.id, u.full_name, u.age, u.city, p.name AS insurance_plan,
                   c.name AS insurance_company
            FROM users u
            JOIN insurance_plans p ON p.id = u.insurance_plan_id
            JOIN insurance_companies c ON c.id = p.company_id
            ORDER BY u.id
            """
        ).fetchall()
        return rows_to_dicts(rows)


def get_user(user_id: int) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT u.id, u.full_name, u.age, u.city, u.insurance_plan_id,
                   p.name AS insurance_plan, p.annual_deductible_cents,
                   p.coinsurance_percent, p.max_coverage_cents,
                   c.name AS insurance_company
            FROM users u
            JOIN insurance_plans p ON p.id = u.insurance_plan_id
            JOIN insurance_companies c ON c.id = p.company_id
            WHERE u.id = ?
            """,
            (user_id,),
        ).fetchone()
        return dict(row) if row else None


def create_conversation(user_id: int) -> dict[str, Any]:
    if not get_user(user_id):
        raise ValueError("User not found")
    conversation_id = str(uuid.uuid4())
    thread_id = f"conversation:{conversation_id}"
    with connect() as conn:
        conn.execute(
            "INSERT INTO conversations (id, user_id, thread_id) VALUES (?, ?, ?)",
            (conversation_id, user_id, thread_id),
        )
    return {"conversation_id": conversation_id, "user_id": user_id, "thread_id": thread_id}


def get_conversation(conversation_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT id, user_id, thread_id, created_at, updated_at FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
        return dict(row) if row else None


def list_conversations(user_id: int) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT c.id AS conversation_id, c.user_id, c.created_at, c.updated_at,
                   (
                       SELECT m.content
                       FROM messages m
                       WHERE m.conversation_id = c.id
                       ORDER BY m.id DESC
                       LIMIT 1
                   ) AS last_message
            FROM conversations c
            WHERE c.user_id = ?
            ORDER BY c.updated_at DESC
            """,
            (user_id,),
        ).fetchall()
        return rows_to_dicts(rows)


def add_message(conversation_id: str, role: str, content: str, metadata: dict[str, Any] | None = None) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO messages (conversation_id, role, content, metadata_json)
            VALUES (?, ?, ?, ?)
            """,
            (conversation_id, role, content, json.dumps(metadata or {})),
        )
        conn.execute(
            "UPDATE conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (conversation_id,),
        )


def get_messages(conversation_id: str) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT role, content, metadata_json, created_at
            FROM messages
            WHERE conversation_id = ?
            ORDER BY id
            """,
            (conversation_id,),
        ).fetchall()
    messages = []
    for row in rows:
        item = dict(row)
        item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
        messages.append(item)
    return messages


def list_specialties() -> list[dict[str, Any]]:
    with connect() as conn:
        return rows_to_dicts(conn.execute("SELECT * FROM specialties ORDER BY id").fetchall())


def classify_specialty(symptoms: str) -> dict[str, Any]:
    normalized = symptoms.lower()
    specialties = list_specialties()
    best = None
    best_score = -1
    for specialty in specialties:
        keywords = [kw.strip() for kw in specialty["keywords"].split(",")]
        score = sum(1 for keyword in keywords if keyword and keyword in normalized)
        if score > best_score:
            best = specialty
            best_score = score
    if not best or best_score <= 0:
        best = next(s for s in specialties if s["name"] == "Medicina Interna")
    urgency_words = ("desmayo", "sangrado fuerte", "dificultad respirar", "dolor intenso", "accidente")
    if any(word in normalized for word in urgency_words):
        best = next(s for s in specialties if s["name"] == "Emergencia")
    return {"id": best["id"], "name": best["name"], "description": best["description"]}


def calculate_best_option(user_id: int, symptoms: str) -> dict[str, Any]:
    user = get_user(user_id)
    if not user:
        raise ValueError("User not found")
    specialty = classify_specialty(symptoms)
    plan_id = user["insurance_plan_id"]
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT h.id AS hospital_id, h.name AS hospital_name, h.city, h.network_tier,
                   hp.list_price_cents, ic.negotiated_price_cents, ic.fixed_copay_cents,
                   ic.coverage_percent, ic.in_network
            FROM hospitals h
            JOIN hospital_specialty_prices hp
              ON hp.hospital_id = h.id AND hp.specialty_id = ?
            LEFT JOIN insurance_contracts ic
              ON ic.hospital_id = h.id AND ic.specialty_id = ? AND ic.plan_id = ?
            ORDER BY h.id
            """,
            (specialty["id"], specialty["id"], plan_id),
        ).fetchall()

    options = []
    for row in rows:
        item = dict(row)
        in_network = bool(item["in_network"])
        negotiated = item["negotiated_price_cents"] if in_network else item["list_price_cents"]
        fixed_copay = item["fixed_copay_cents"] if in_network else None
        coverage_percent = item["coverage_percent"] if in_network else 0
        insurer_payment = negotiated * coverage_percent // 100 if in_network else 0
        coinsurance_patient = negotiated - insurer_payment
        patient_cost = max(fixed_copay or 0, coinsurance_patient) if in_network else negotiated
        options.append(
            {
                "hospital_id": item["hospital_id"],
                "hospital_name": item["hospital_name"],
                "city": item["city"],
                "network_tier": item["network_tier"],
                "in_network": in_network,
                "list_price_cents": item["list_price_cents"],
                "negotiated_price_cents": negotiated,
                "coverage_percent": coverage_percent,
                "fixed_copay_cents": fixed_copay,
                "patient_cost_cents": patient_cost,
                "insurance_covers_cents": max(0, negotiated - patient_cost),
            }
        )
    options.sort(key=lambda option: (option["patient_cost_cents"], not option["in_network"]))
    return {
        "user": user,
        "specialty": specialty,
        "best_option": options[0] if options else None,
        "alternatives": options,
    }
