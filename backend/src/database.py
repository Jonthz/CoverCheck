from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parents[1] / "app.db"
SEED_VERSION = "2"
logger = logging.getLogger(__name__)


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS app_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

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
        current_version = conn.execute(
            "SELECT value FROM app_metadata WHERE key = 'seed_version'"
        ).fetchone()
        has_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0
        if not has_users or not current_version or current_version["value"] != SEED_VERSION:
            logger.info("Reseeding SQLite demo database at %s with seed version %s", DB_PATH, SEED_VERSION)
            reset_seed_data(conn)
            seed_db(conn)
            conn.execute(
                "INSERT OR REPLACE INTO app_metadata (key, value) VALUES ('seed_version', ?)",
                (SEED_VERSION,),
            )
        else:
            logger.info("SQLite database ready at %s", DB_PATH)


def reset_seed_data(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM messages")
    conn.execute("DELETE FROM conversations")
    conn.execute("DELETE FROM insurance_contracts")
    conn.execute("DELETE FROM hospital_specialty_prices")
    conn.execute("DELETE FROM hospitals")
    conn.execute("DELETE FROM specialties")
    conn.execute("DELETE FROM users")
    conn.execute("DELETE FROM insurance_plans")
    conn.execute("DELETE FROM insurance_companies")


def seed_db(conn: sqlite3.Connection) -> None:
    conn.executemany(
        "INSERT INTO insurance_companies (id, name) VALUES (?, ?)",
        [(1, "SaludTotal"), (2, "AndesCare"), (3, "PacificMed")],
    )
    conn.executemany(
        """
        INSERT INTO insurance_plans
        (id, company_id, name, annual_deductible_cents, coinsurance_percent, max_coverage_cents)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (1, 1, "SaludTotal Preferente", 10000, 12, 600000),
            (2, 1, "SaludTotal Basico", 30000, 28, 280000),
            (3, 2, "AndesCare Premium", 5000, 8, 900000),
            (4, 3, "PacificMed Familiar", 15000, 18, 500000),
        ],
    )
    conn.executemany(
        "INSERT INTO users (id, full_name, age, city, insurance_plan_id) VALUES (?, ?, ?, ?, ?)",
        [
            (1, "Ana Perez", 34, "Quito", 1),
            (2, "Carlos Rivas", 47, "Quito", 2),
            (3, "Mia Torres", 8, "Guayaquil", 3),
            (4, "Lucia Andrade", 29, "Guayaquil", 4),
        ],
    )
    specialties = [
        (1, "Cardiologia", "Dolor de pecho, palpitaciones, hipertension y seguimiento cardiovascular.", "pecho,corazon,palpitaciones,presion,aire,taquicardia"),
        (2, "Pediatria", "Atencion medica para ninos y adolescentes.", "nino,nina,bebe,fiebre infantil,pediatria,vomito infantil"),
        (3, "Dermatologia", "Piel, alergias, ronchas, acne y erupciones.", "piel,ronchas,acne,erupcion,alergia,manchas,picazon"),
        (4, "Traumatologia", "Golpes, fracturas, lesiones musculares o articulares.", "fractura,golpe,rodilla,hombro,dolor muscular,torcedura,caida"),
        (5, "Medicina Interna", "Sintomas generales en adultos y evaluacion integral.", "fiebre,dolor cabeza,gripe,cansancio,malestar,tos,nausea"),
        (6, "Emergencia", "Sintomas potencialmente urgentes o de atencion inmediata.", "desmayo,sangrado fuerte,dificultad respirar,dolor intenso,accidente,convulsion"),
        (7, "Gastroenterologia", "Dolor abdominal, reflujo, diarrea, gastritis y digestion.", "estomago,abdomen,gastritis,diarrea,reflujo,vomito,acidez"),
        (8, "Neurologia", "Migranas, mareos, hormigueos, convulsiones y sintomas neurologicos.", "migrana,mareo,hormigueo,convulsion,memoria,temblor"),
    ]
    conn.executemany(
        "INSERT INTO specialties (id, name, description, keywords) VALUES (?, ?, ?, ?)",
        specialties,
    )
    hospitals = [
        (1, "Hospital Metropolitano", "Quito", "premium"),
        (2, "Clinica Norte", "Quito", "preferente"),
        (3, "Hospital del Valle", "Quito", "standard"),
        (4, "Centro Medico La Carolina", "Quito", "economico"),
        (5, "Clinica Pacifico", "Guayaquil", "preferente"),
        (6, "Hospital Santa Lucia", "Guayaquil", "standard"),
        (7, "Centro Familiar Kennedy", "Guayaquil", "economico"),
    ]
    conn.executemany(
        "INSERT INTO hospitals (id, name, city, network_tier) VALUES (?, ?, ?, ?)",
        hospitals,
    )

    base_prices = {
        1: [14500, 11800, 12800, 9800, 13200, 11000, 9200],
        2: [9200, 7600, 8100, 6400, 8400, 7000, 6100],
        3: [10500, 8200, 9600, 6900, 9300, 7800, 6600],
        4: [12200, 9000, 10400, 7600, 10800, 8600, 7300],
        5: [8700, 6500, 7400, 5600, 7600, 6300, 5400],
        6: [24000, 19500, 21000, 18000, 22000, 19000, 17000],
        7: [11200, 8300, 9500, 7200, 9800, 8100, 6900],
        8: [13800, 10800, 12000, 8800, 12400, 10200, 8400],
    }
    prices = [
        (hospital_id, specialty_id, amount)
        for specialty_id, amounts in base_prices.items()
        for hospital_id, amount in enumerate(amounts, start=1)
    ]
    conn.executemany(
        "INSERT INTO hospital_specialty_prices (hospital_id, specialty_id, list_price_cents) VALUES (?, ?, ?)",
        prices,
    )

    plan_rules = {
        1: {
            1: (1, 78, 82, 2800),
            2: (1, 70, 88, 2200),
            3: (1, 74, 80, 2600),
            4: (1, 68, 76, 1800),
            5: (0, 100, 0, None),
            6: (0, 100, 0, None),
            7: (0, 100, 0, None),
        },
        2: {
            1: (0, 100, 0, None),
            2: (1, 82, 62, 4200),
            3: (1, 84, 68, 3900),
            4: (1, 72, 58, 3200),
            5: (1, 86, 55, 4500),
            6: (1, 88, 60, 4300),
            7: (1, 76, 50, 3500),
        },
        3: {
            1: (1, 72, 92, 1800),
            2: (0, 100, 0, None),
            3: (1, 70, 90, 1600),
            4: (0, 100, 0, None),
            5: (1, 74, 88, 1900),
            6: (1, 72, 90, 1700),
            7: (1, 66, 86, 1400),
        },
        4: {
            1: (0, 100, 0, None),
            2: (1, 86, 72, 3100),
            3: (0, 100, 0, None),
            4: (1, 74, 68, 2500),
            5: (1, 78, 78, 2700),
            6: (1, 80, 76, 2600),
            7: (1, 70, 70, 2100),
        },
    }
    specialty_adjustments = {1: 900, 2: 0, 3: 300, 4: 500, 5: 0, 6: 2200, 7: 400, 8: 700}
    contracts = []
    contract_id = 1
    for plan_id, hospital_rules in plan_rules.items():
        for hospital_id, (in_network, negotiated_factor, coverage, base_copay) in hospital_rules.items():
            for specialty_id, amounts in base_prices.items():
                list_price = amounts[hospital_id - 1]
                negotiated = list_price * negotiated_factor // 100
                copay = None if base_copay is None else base_copay + specialty_adjustments[specialty_id]
                contracts.append(
                    (contract_id, plan_id, hospital_id, specialty_id, negotiated, copay, coverage, in_network)
                )
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


def get_user_insurance(user_id: int) -> dict[str, Any] | None:
    return get_user(user_id)


def list_hospitals() -> list[dict[str, Any]]:
    with connect() as conn:
        return rows_to_dicts(conn.execute("SELECT * FROM hospitals ORDER BY city, name").fetchall())


def list_specialties() -> list[dict[str, Any]]:
    with connect() as conn:
        return rows_to_dicts(conn.execute("SELECT * FROM specialties ORDER BY name").fetchall())


def list_user_coverage(user_id: int) -> list[dict[str, Any]]:
    user = get_user(user_id)
    if not user:
        raise ValueError("User not found")
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT h.id AS hospital_id, h.name AS hospital_name, h.city, h.network_tier,
                   s.id AS specialty_id, s.name AS specialty_name,
                   hp.list_price_cents, ic.negotiated_price_cents, ic.fixed_copay_cents,
                   ic.coverage_percent, ic.in_network
            FROM hospitals h
            JOIN hospital_specialty_prices hp ON hp.hospital_id = h.id
            JOIN specialties s ON s.id = hp.specialty_id
            LEFT JOIN insurance_contracts ic
              ON ic.hospital_id = h.id AND ic.specialty_id = s.id AND ic.plan_id = ?
            ORDER BY h.city, h.name, s.name
            """,
            (user["insurance_plan_id"],),
        ).fetchall()
    return rows_to_dicts(rows)


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


def delete_conversation(user_id: int, conversation_id: str) -> bool:
    with connect() as conn:
        conversation = conn.execute(
            "SELECT id FROM conversations WHERE id = ? AND user_id = ?",
            (conversation_id, user_id),
        ).fetchone()
        if not conversation:
            return False
        conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
        conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
        return True


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
    urgency_words = ("desmayo", "sangrado fuerte", "dificultad respirar", "dolor intenso", "accidente", "pecho")
    if any(word in normalized for word in urgency_words) and any(word in normalized for word in ("pecho", "respirar", "desmayo")):
        best = next(s for s in specialties if s["name"] == "Emergencia")
    return {"id": best["id"], "name": best["name"], "description": best["description"]}


def _option_reason(option: dict[str, Any]) -> str:
    if option["in_network"]:
        return (
            f"En red: precio negociado de {option['negotiated_price_cents'] / 100:.2f}, "
            f"cobertura del {option['coverage_percent']}% y copago fijo de "
            f"{(option['fixed_copay_cents'] or 0) / 100:.2f}."
        )
    return "Fuera de red: el paciente asume el precio de lista porque no hay cobertura contratada."


def _selection_reason(best: dict[str, Any], options: list[dict[str, Any]]) -> str:
    tied = [option for option in options if option["patient_cost_cents"] == best["patient_cost_cents"]]
    if len(tied) > 1:
        names = ", ".join(option["hospital_name"] for option in tied)
        return (
            f"{best['hospital_name']} fue seleccionado porque comparte el menor costo para el paciente "
            f"({best['patient_cost_cents'] / 100:.2f}) con {names}; se priorizo estar en red y el orden de ranking del plan."
        )
    return (
        f"{best['hospital_name']} fue seleccionado porque tiene el menor costo final para el paciente "
        f"({best['patient_cost_cents'] / 100:.2f}) despues de aplicar precio negociado, copago y cobertura."
    )


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
        option = {
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
        option["reason"] = _option_reason(option)
        options.append(option)
    options.sort(key=lambda option: (option["patient_cost_cents"], not option["in_network"], option["hospital_id"]))
    best = options[0] if options else None
    return {
        "user": user,
        "specialty": specialty,
        "best_option": best,
        "alternatives": options,
        "all_options": options,
        "selection_reason": _selection_reason(best, options) if best else "No hay hospitales disponibles para comparar.",
    }
