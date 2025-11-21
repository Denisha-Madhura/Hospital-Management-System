import sqlite3
import hashlib
from datetime import datetime, timedelta

DATABASE = 'hms.db'

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def create_user(username, password, name, contact_info, role='Patient'):
    conn = get_db_connection()
    cursor = conn.cursor()
    hashed_pass = hash_password(password)

    try:
        cursor.execute(
            "INSERT INTO users (username, password_has, role, name, contact_info) VALUES (?, ?, ?, ?, ?)",
            (username, hashed_pass, role, name, contact_info)
        )

        user_id = cursor.lastrowid
        conn.commit()
        return user_id
    except sqlite3.IntegrityError:
        return None
    finally:
        conn.close()

def add_department(name, description):
    conn = get_db_connection()
    try: 
        conn.execute("INSERT OR IGNORE INTO departments (name, description) VALUES (?,?)", (name, description))
        conn.commit()
    finally:
        conn.close()

def get_departments():
    conn = get_db_connection()
    departments = conn.execute("""
    SELECT
        d.id, 
        d.name, 
        COUNT(doc.user_id) AS doctor_count
    FROM departments d
    LEFT JOIN doctors doc ON d.id = doc.specializaiton_id
    GROUP BY d.id, d.name
    ORDER BY d.name
                               """).fetchall()
    conn.close()
    return departments

def add_doctor_profile(user_id, specializaition_id):
    conn = get_db_connection()
    try: 
        conn.execute(
            "INSERT INTO doctors (user_id, specialization_id) VALUES (?, ?)", (user_id, specializaition_id)
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def set_doctor_availability(doctor_id, date, start_time, end_time):
    conn = get_db_connection()
    try:
        conn.execute(
            """INSERT INTO doctor_availbility (doctor_id, date, start_time, end_time) VALUES (?, ?, ?, ?)""", (doctor_id, date, start_time, end_time)
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def get_doctor_availability(doctor_id, start_date, end_date):
    conn = get_db_connection()
    availability = conn.execute(
        """
    SELECT date, start_time, end_time FROM doctor_availability
    WHERE doctor_id = ? AND date BETWEEN ? AND ?
    ORDER BY date, start_time""", 
    (doctor_id, start_date, end_date)
    ).fetchall()
    conn.close()
    return availability

def get_available_doctors(specialization_id = None, name_query = None):
    conn = get_db_connection()
    query = """
    SELECT
        u.id, u.name, u.contact_info, d.name AS specialization
    FROM users u
    JOIN doctors doc ON u.id = doc.user_id
    WHERE u.role = "Doctor" AND u.is_active = 1
    """

    params = []

    if specialization_id:
        query += "AND d.id = ?"
        params.append(specialization_id)

    if name_query:
        query += "AND u.name LIKE ?"
        params.append(f"%{name_query}%")

    query += " ORDER BY u.name"

    doctors = conn.execute(query, tuple(params)).fetchall()
    conn.close()
    return doctors

def get_doctor_availability_by_date(doctor_id, date_str):
    conn = get_db_connection()
    available_slots = conn.execute(
        "SELECT start_time FROM doctor_availability WHERE doctor_id = ? AND date = ?", 
        (doctor_id, date_str)
    ).fetchall()


    booked_times = conn.execute(
        "SELECT time FROM appointments WHERE doctor_id = ? AND date = ? AND status = 'Booked' ",
        (doctor_id, date_str)
    ).fetchall()

    booked_times = {t['time'] for t in booked_times}

    open_slots = [
        slot['start_time'] for slot in available_slots
        if slot['start_time'] not in booked_times
    ]

    conn.close()
    return open_slots

def create_appointment(patient_id, doctor_id, date_str, time):
    conn = get_db_connection()

    try:
        conn.execute("""
            INSERT INTO appointments (patient_id, doctor_id, date, time, status)
            VALUES (?, ?, ?, ?, 'Booked')""",
            (patient_id, doctor_id, date_str, time))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def get_patient_appointments(patient_id):
    conn = get_db_connection()
    appointments = conn.execute(
        """
        SELECT
        a.id AS appt_id, a.date, a.time, a.status
        u_doc.name AS doctor_name, 
        d.name AS specialization,
        t.diagnosis, t.prescription
        FROM appointments a
        JOIN users u_doc ON a.doctor_id = u_doc.id
        JOIN doctors doc ON u_doc.id = doc.user_id
        JOIN departments d ON doc.specialization_id = d.id
        LEFT JOIN treatements t ON a.id = t.appointment_id
        WHERE a.patient_id = ?
        ORDER BY a.date DESC, a.time DESC
        """, (patient_id,)
    ).fetchall()

    conn.close()
    return appointments

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    #users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT
            username TEXT NOT NULL UNIQUE
            password_has TEXT NOT NULL
            role TEXT NOT NULL, -- 'Admin', 'Doctor', 'Patient'
            name TEXT,
            contact_info TEXT,
            is_active BOOLEAN DEFAULT 1
        );
                   ''')
    
    #departments table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS departments(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
            description TEXT
        );
                   ''')
    
    #doctors table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS doctors(
            user_id INTEGER PRIMARY KEY, 
            specialization_id INTEGER,
            FOREIGN KEY (user_id) REFERENCES users (id)
            FOREIGN KEY (specialization_id) REFERENCES departments (id)
        );
                   ''')
    
    #doctor availability table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS doctor_availability(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doctor_id INTEGER NOT NULL
                   date TEXT NOT NULL, -- YY-MM-DD
                   start_time TEXT NOT NULL, -- HH:MM
                   end_time TEXT NOT NULL, --HH:MM
                   UNIQUE(doctor_id, date, start_time),
                   FOREIGN KEY (doctor_id) REFERENCES users (id)
        );
    ''')

    #appointments table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS appointments (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            patient_id INTEGER NOT NULL
            doctor_id INTEGER NOT NULL
            date TEXT NOT NULL, --YYYY-MM-DD
            time TEXT NOT NULL, --HH:MM
            status TEXT NOT NULL, --'Booked', 'Completed', 'Cancelled'
            UNIQUE(doctor_id, date, time)
            FOREIGN KEY (patient_id) REFERENCES users (id),
            FOREIGN KEY (doctor_id) REFERENCES users (id)
        );
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS treatements (
            id INTEGER PRIMARY KEY AUTOINCREMENT
            appointment_id INTEGER NOT NULL
            diagnosis TEXT,
            prescription TEXT, 
            notes TEXT, 
            date_recorded TEXT,
            FOREIGN KEY (appointment_id) REFERENCES appointments (id)
        );
    ''')

    conn.commit()
    conn.close()

def add_admin():
    conn = get_db_connection()
    cursor = conn.cursor()

    ADMIN_USERNAME = 'admin'
    ADMIN_PASSWORD = 'adminpassword'
    hashed_pass = hash_password(ADMIN_PASSWORD)

    try:
        cursor.execute("SELECT id FROM users WHERE username = ?", (ADMIN_USERNAME, ))
        if cursor.fetchone() is None:
            cursor.execute(
                "INSERT INTO users (username, password_hash, role, name) VALUES (?, ?, ?, ?)", 
                (ADMIN_USERNAME, hashed_pass, 'Admin', 'System Administrator')
            )
            print(f"Admin user '{ADMIN_USERNAME}' created")
            conn.commit()
        else:
            print(f"Admin user {ADMIN_USERNAME} already exists")
    except sqlite3.IntegrityError as e:
        print(f"Integrity error while adding admin: {e}")
    finally:
        conn.close()

if __name__ == '__main__':
    init_db()
    add_admin()
    print("Database initialized")