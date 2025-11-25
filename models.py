import sqlite3
import hashlib
from datetime import datetime, timedelta # Import timedelta

# Define the path for the SQLite database file
DATABASE = 'hms.db'

def get_db_connection():
    """Establishes a connection to the SQLite database."""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row # Allows accessing columns by name
    return conn

def hash_password(password):
    """Hashes a password for secure storage."""
    # Using SHA-256 for a basic example. In a real application, use a proper library like bcrypt.
    return hashlib.sha256(password.encode()).hexdigest()

def create_user(username, password, name, contact_info, role='Patient'):
    """Inserts a new user record into the database."""
    conn = get_db_connection()
    cursor = conn.cursor()
    hashed_pass = hash_password(password)
    
    try:
        cursor.execute(
            "INSERT INTO users (username, password_hash, role, name, contact_info) VALUES (?, ?, ?, ?, ?)",
            (username, hashed_pass, role, name, contact_info)
        )
        user_id = cursor.lastrowid
        conn.commit()
        return user_id
    except sqlite3.IntegrityError:
        # This error is usually thrown if the username is not unique
        return None
    finally:
        conn.close()

# --- DOCTOR MANAGEMENT FUNCTIONS ---

def add_department(name, description):
    """Adds a specialization/department if it doesn't already exist."""
    conn = get_db_connection()
    try:
        conn.execute("INSERT OR IGNORE INTO departments (name, description) VALUES (?, ?)", (name, description))
        conn.commit()
    finally:
        conn.close()

def get_departments():
    """Fetches all departments from the database."""
    conn = get_db_connection()
    # Also count active doctors in each department
    departments = conn.execute("""
        SELECT 
            d.id, 
            d.name,
            COUNT(doc.user_id) AS doctor_count
        FROM departments d
        LEFT JOIN doctors doc ON d.id = doc.specialization_id
        GROUP BY d.id, d.name
        ORDER BY d.name
    """).fetchall()
    conn.close()
    return departments

def add_doctor_profile(user_id, specialization_id):
    """Links a Doctor user to a specialization profile."""
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO doctors (user_id, specialization_id) VALUES (?, ?)",
            (user_id, specialization_id)
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

# --- DOCTOR AVAILABILITY FUNCTIONS ---

def set_doctor_availability(doctor_id, date, start_time, end_time):
    """Sets a specific time slot for a doctor."""
    conn = get_db_connection()
    try:
        conn.execute(
            """INSERT INTO doctor_availability (doctor_id, date, start_time, end_time) 
               VALUES (?, ?, ?, ?)""",
            (doctor_id, date, start_time, end_time)
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        # Prevents duplicate slots (UNIQUE constraint)
        return False
    finally:
        conn.close()

def get_doctor_availability(doctor_id, start_date, end_date):
    """Fetches availability slots for a doctor within a date range."""
    conn = get_db_connection()
    # Note: We order by date and time for clean display
    availability = conn.execute(
        """SELECT date, start_time, end_time FROM doctor_availability 
           WHERE doctor_id = ? AND date BETWEEN ? AND ? 
           ORDER BY date, start_time""",
        (doctor_id, start_date, end_date)
    ).fetchall()
    conn.close()
    return availability

# --- NEW PATIENT BOOKING FUNCTIONS ---

def get_available_doctors(specialization_id=None, name_query=None):
    """Fetches doctors filtered by specialization or name."""
    conn = get_db_connection()
    query = """
        SELECT 
            u.id, u.name, u.contact_info, d.name AS specialization 
        FROM users u
        JOIN doctors doc ON u.id = doc.user_id
        JOIN departments d ON doc.specialization_id = d.id
        WHERE u.role = 'Doctor' AND u.is_active = 1
    """
    params = []

    if specialization_id:
        query += " AND d.id = ?"
        params.append(specialization_id)
    
    if name_query:
        # Simple LIKE search for doctor name
        query += " AND u.name LIKE ?"
        params.append(f"%{name_query}%")
        
    query += " ORDER BY u.name"
    
    doctors = conn.execute(query, tuple(params)).fetchall()
    conn.close()
    return doctors

def get_doctor_availability_by_date(doctor_id, date_str):
    """
    Finds available time slots for a specific doctor on a specific date.
    This also accounts for already booked appointments.
    """
    conn = get_db_connection()
    
    # 1. Get all scheduled availability slots for the doctor on that date
    available_slots = conn.execute(
        "SELECT start_time FROM doctor_availability WHERE doctor_id = ? AND date = ?",
        (doctor_id, date_str)
    ).fetchall()
    
    # 2. Get all currently booked appointments for the doctor on that date
    booked_times = conn.execute(
        "SELECT time FROM appointments WHERE doctor_id = ? AND date = ? AND status = 'Booked'",
        (doctor_id, date_str)
    ).fetchall()
    
    booked_times = {t['time'] for t in booked_times}
    
    # 3. Filter available slots to remove booked times
    open_slots = [
        slot['start_time'] for slot in available_slots 
        if slot['start_time'] not in booked_times
    ]

    conn.close()
    return open_slots

def create_appointment(patient_id, doctor_id, date_str, time):
    """Creates a new 'Booked' appointment."""
    conn = get_db_connection()
    
    # Basic check to prevent double booking, although a UNIQUE constraint exists
    try:
        conn.execute(
            """INSERT INTO appointments (patient_id, doctor_id, date, time, status)
               VALUES (?, ?, ?, ?, 'Booked')""",
            (patient_id, doctor_id, date_str, time)
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False # Doctor is already booked at this time
    finally:
        conn.close()

def get_patient_appointments(patient_id):
    """Fetches all past, upcoming, and cancelled appointments for a patient."""
    conn = get_db_connection()
    
    appointments = conn.execute("""
        SELECT 
            a.id AS appt_id, a.date, a.time, a.status,
            u_doc.name AS doctor_name,
            d.name AS specialization,
            t.diagnosis, t.prescription
        FROM appointments a
        JOIN users u_doc ON a.doctor_id = u_doc.id
        JOIN doctors doc ON u_doc.id = doc.user_id
        JOIN departments d ON doc.specialization_id = d.id
        LEFT JOIN treatments t ON a.id = t.appointment_id
        WHERE a.patient_id = ?
        ORDER BY a.date DESC, a.time DESC
    """, (patient_id,)).fetchall()
    
    conn.close()
    return appointments


# --- DB INIT (Rest of the file remains the same) ---
def init_db():
    """Initializes the database by creating tables and seeding the Admin user."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # --- 1. Users Table (Handles Admin, Doctor, Patient) ---
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL, -- 'Admin', 'Doctor', 'Patient'
            name TEXT,
            contact_info TEXT,
            is_active BOOLEAN DEFAULT 1 -- Used for blacklisting/removing users
        );
    ''')

    # --- 2. Departments Table (Specializations) ---
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS departments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT
        );
    ''')

    # --- 3. Doctors Table (Doctor Profile) ---
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS doctors (
            user_id INTEGER PRIMARY KEY,
            specialization_id INTEGER,
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (specialization_id) REFERENCES departments (id)
        );
    ''')

    # --- 4. DoctorAvailability Table (Availability for Appointments) ---
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS doctor_availability (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doctor_id INTEGER NOT NULL,
            date TEXT NOT NULL, -- YYYY-MM-DD
            start_time TEXT NOT NULL, -- HH:MM
            end_time TEXT NOT NULL,   -- HH:MM
            UNIQUE(doctor_id, date, start_time),
            FOREIGN KEY (doctor_id) REFERENCES users (id) -- Changed to users for consistency
        );
    ''')

    # --- 5. Appointments Table ---
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS appointments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            doctor_id INTEGER NOT NULL,
            date TEXT NOT NULL, -- YYYY-MM-DD
            time TEXT NOT NULL, -- HH:MM
            status TEXT NOT NULL, -- 'Booked', 'Completed', 'Cancelled'
            UNIQUE(doctor_id, date, time),
            FOREIGN KEY (patient_id) REFERENCES users (id),
            FOREIGN KEY (doctor_id) REFERENCES users (id)
        );
    ''')

    # --- 6. Treatments Table (Medical Records) ---
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS treatments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            appointment_id INTEGER NOT NULL,
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
    """Programmatically creates the pre-existing Admin user if they do not exist."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    ADMIN_USERNAME = 'admin'
    ADMIN_PASSWORD = 'adminpassword' # Note: Replace with a safer method for production
    hashed_pass = hash_password(ADMIN_PASSWORD)

    try:
        cursor.execute("SELECT id FROM users WHERE username = ?", (ADMIN_USERNAME,))
        if cursor.fetchone() is None:
            # Insert the pre-existing Admin user
            cursor.execute(
                "INSERT INTO users (username, password_hash, role, name) VALUES (?, ?, ?, ?)",
                (ADMIN_USERNAME, hashed_pass, 'Admin', 'System Administrator')
            )
            print(f"Admin user '{ADMIN_USERNAME}' created with password: {ADMIN_PASSWORD}")
            conn.commit()
        else:
            print(f"Admin user '{ADMIN_USERNAME}' already exists.")

    except sqlite3.IntegrityError as e:
        # Handles case where another process might have inserted the admin
        print(f"Integrity Error while adding admin: {e}")
    finally:
        conn.close()

if __name__ == '__main__':
    # Initialize DB and ensure Admin exists when models.py is run directly
    init_db()
    add_admin()
    print("Database initialization complete.")