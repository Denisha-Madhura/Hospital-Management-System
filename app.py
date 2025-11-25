from flask import Flask, render_template, request, redirect, url_for, session, flash, g
from models import init_db, add_admin, get_db_connection, hash_password, create_user, get_departments, add_department, add_doctor_profile, set_doctor_availability, get_doctor_availability, get_available_doctors, get_doctor_availability_by_date, create_appointment, get_patient_appointments # <-- Imported new functions
import os
import hashlib
import sqlite3
from datetime import date, timedelta, datetime # <-- Import datetime utilities

# Initialize Flask App
app = Flask(__name__)
# Flask session secret key (CRITICAL for security)
app.secret_key = os.environ.get('SECRET_KEY', 'a_strong_fallback_secret_key_12345') 

# --- Database Initialization on Startup ---
# This ensures the database file and the Admin user are created when the app starts
with app.app_context():
    init_db()
    add_admin()
    add_department("Cardiology", "Heart and blood vessels.") # Seed default departments
    add_department("Pediatrics", "Children's health.")
    add_department("Orthopedics", "Bones and muscles.")

# --- Before/After Request Hooks ---

@app.before_request
def load_logged_in_user():
    """Load user data from session into the global 'g' object."""
    user_id = session.get('user_id')
    if user_id is None:
        g.user = None
    else:
        conn = get_db_connection()
        g.user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        conn.close()

def login_required(role=None):
    """Decorator to check if a user is logged in and optionally checks their role."""
    def wrapper(f):
        def decorated_function(*args, **kwargs):
            if g.user is None:
                flash("Please log in to access this page.", 'danger')
                return redirect(url_for('login'))
            if role and g.user['role'] != role:
                flash(f"Access denied. You must be a {role}.", 'danger')
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        decorated_function.__name__ = f.__name__ # Preserve original function name
        return decorated_function
    return wrapper

# --- Routes ---

@app.route('/')
def index():
    """The public landing page."""
    return render_template('index.html', title='Welcome to HMS')

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Handles user login authentication."""
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        conn = get_db_connection()
        error = None
        
        user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        conn.close()

        if user is None:
            error = 'Incorrect username.'
        elif user['password_hash'] != hash_password(password):
            # Note: The hash_password function from models.py is used here for verification
            error = 'Incorrect password.'

        if error is None:
            session.clear()
            session['user_id'] = user['id']
            session['role'] = user['role']
            flash(f"Welcome, {user['name']} ({user['role']})!", 'success')
            return redirect(url_for('dashboard'))
        
        flash(error, 'danger')
        
    return render_template('login.html', title='Login')

# --- REGISTRATION ROUTE ---
@app.route('/register', methods=['POST'])
def register():
    """Handles patient registration form submission."""
    username = request.form.get('username')
    password = request.form.get('password')
    confirm_password = request.form.get('confirm_password')
    name = request.form.get('name')
    contact_info = request.form.get('contact_info')
    
    # Simple form validation
    if not all([username, password, confirm_password, name, contact_info]):
        flash('All fields are required.', 'danger')
        return redirect(url_for('patient_dashboard')) # Redirect back to the form
        
    if password != confirm_password:
        flash('Passwords do not match.', 'danger')
        return redirect(url_for('patient_dashboard'))
    
    # Attempt to create user (Role is defaulted to 'Patient' in create_user)
    user_id = create_user(username, password, name, contact_info)
    
    if user_id is not None:
        # Registration successful, log the user in immediately
        session.clear()
        session['user_id'] = user_id
        session['role'] = 'Patient'
        flash(f"Registration successful! Welcome, {name}.", 'success')
        return redirect(url_for('patient_dashboard'))
    else:
        # Username already exists (IntegrityError caught in models.py)
        flash('Registration failed. The username may already be taken.', 'danger')
        return redirect(url_for('patient_dashboard'))


@app.route('/logout')
def logout():
    """Handles user logout."""
    session.clear()
    flash("You have been logged out.", 'info')
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required()
def dashboard():
    """Redirects user to the appropriate dashboard based on their role."""
    if g.user['role'] == 'Admin':
        return redirect(url_for('admin_dashboard'))
    elif g.user['role'] == 'Doctor':
        return redirect(url_for('doctor_dashboard'))
    elif g.user['role'] == 'Patient':
        return redirect(url_for('patient_dashboard'))
    return redirect(url_for('index'))

# --- Role-Specific Dashboards ---

@app.route('/admin/dashboard')
@login_required(role='Admin')
def admin_dashboard():
    """Admin dashboard showing overall system statistics."""
    conn = get_db_connection()
    
    # 1. Count Doctors (Users where role='Doctor')
    doctor_count = conn.execute("SELECT COUNT(id) FROM users WHERE role = 'Doctor'").fetchone()[0]
    
    # 2. Count Patients (Users where role='Patient')
    patient_count = conn.execute("SELECT COUNT(id) FROM users WHERE role = 'Patient'").fetchone()[0]
    
    # 3. Count Total Appointments
    appointment_count = conn.execute("SELECT COUNT(id) FROM appointments").fetchone()[0]
    
    conn.close()

    context = {
        'doctor_count': doctor_count,
        'patient_count': patient_count,
        'appointment_count': appointment_count
    }

    flash("Admin Dashboard loaded successfully. System overview displayed.", 'success')
    return render_template('dashboards/admin.html', title='Admin Dashboard', **context)

# --- DOCTOR DASHBOARD AND AVAILABILITY ---

@app.route('/doctor/dashboard')
@login_required(role='Doctor')
def doctor_dashboard():
    """Doctor Dashboard displaying appointments, patient lists, and availability."""
    doctor_id = g.user['id']
    conn = get_db_connection()
    
    today = date.today().strftime('%Y-%m-%d')
    
    # 1. Upcoming Appointments (Today/Future)
    upcoming_appointments = conn.execute("""
        SELECT a.id, a.date, a.time, u.name AS patient_name, u.contact_info
        FROM appointments a
        JOIN users u ON a.patient_id = u.id
        WHERE a.doctor_id = ? AND a.status = 'Booked' AND a.date >= ?
        ORDER BY a.date, a.time
    """, (doctor_id, today)).fetchall()
    
    # 2. List of All Unique Patients Assigned to this Doctor (via past/upcoming appointments)
    patient_list = conn.execute("""
        SELECT DISTINCT u.id, u.name, u.contact_info
        FROM appointments a
        JOIN users u ON a.patient_id = u.id
        WHERE a.doctor_id = ?
        ORDER BY u.name
    """, (doctor_id,)).fetchall()
    
    # 3. Availability for the next 7 days
    start_date = date.today().strftime('%Y-%m-%d')
    end_date = (date.today() + timedelta(days=6)).strftime('%Y-%m-%d')
    availability_slots = get_doctor_availability(doctor_id, start_date, end_date)

    conn.close()

    context = {
        'upcoming_appointments': upcoming_appointments,
        'patient_list': patient_list,
        'availability_slots': availability_slots,
        'today': today,
        'end_date': end_date
    }

    flash("Doctor Dashboard loaded successfully.", 'success')
    return render_template('dashboards/doctor.html', title='Doctor Dashboard', **context)

@app.route('/doctor/availability', methods=['POST'])
@login_required(role='Doctor')
def doctor_availability():
    """Handles submission of doctor availability form."""
    doctor_id = g.user['id']
    
    # Process the form data
    date_str = request.form.get('date')
    start_time = request.form.get('start_time')
    end_time = request.form.get('end_time')
    
    # Input validation
    if not all([date_str, start_time, end_time]):
        flash("All date and time fields are required.", 'danger')
        return redirect(url_for('doctor_dashboard'))

    try:
        # Basic date format validation (YYYY-MM-DD)
        datetime.strptime(date_str, '%Y-%m-%d')
        
        # Check if the date is in the past
        if date_str < date.today().strftime('%Y-%m-%d'):
            flash("You cannot set availability for a past date.", 'danger')
            return redirect(url_for('doctor_dashboard'))

    except ValueError:
        flash("Invalid date format. Use YYYY-MM-DD.", 'danger')
        return redirect(url_for('doctor_dashboard'))
    
    
    if set_doctor_availability(doctor_id, date_str, start_time, end_time):
        flash(f"Availability set for {date_str} from {start_time} to {end_time}.", 'success')
    else:
        flash("Error: That exact slot is already set or a database error occurred.", 'warning')
        
    return redirect(url_for('doctor_dashboard'))

# --- END DOCTOR ROUTES ---

@app.route('/patient/dashboard')
def patient_dashboard(): 
    """Handles Patient dashboard display (if logged in) or Registration (if logged out)."""
    # If a patient is logged in, they see their dashboard and history
    if g.user and g.user['role'] == 'Patient':
        patient_id = g.user['id']
        appointments = get_patient_appointments(patient_id)
        
        # Separate appointments into Upcoming and History (Completed/Cancelled)
        upcoming = []
        history = []
        today_date_str = date.today().strftime('%Y-%m-%d')
        
        for appt in appointments:
            if appt['status'] == 'Booked' and appt['date'] >= today_date_str:
                upcoming.append(appt)
            else:
                history.append(appt)
        
        context = {
            'user': g.user,
            'upcoming_appointments': upcoming,
            'appointment_history': history,
        }
        flash("Patient Dashboard and Appointment History loaded.", 'success')
        return render_template('dashboards/patient.html', title='Patient Dashboard', **context)

    # If the user is logged out, they see the registration form
    return render_template('dashboards/patient.html', title='Patient Registration')


@app.route('/patient/book', methods=['GET', 'POST'])
@login_required(role='Patient')
def patient_book_appointment():
    """Handles doctor search and appointment booking."""
    departments = get_departments()
    doctors = []
    
    # Handle Doctor Search (GET request)
    if request.method == 'GET':
        selected_dept_id = request.args.get('specialization_id')
        doctor_name_query = request.args.get('doctor_name_query')
        
        if selected_dept_id or doctor_name_query:
            doctors = get_available_doctors(
                specialization_id=selected_dept_id, 
                name_query=doctor_name_query
            )

    # Handle Appointment Booking (POST request)
    elif request.method == 'POST':
        patient_id = g.user['id']
        doctor_id = request.form.get('doctor_id')
        date_str = request.form.get('date')
        time = request.form.get('time')
        
        if not all([doctor_id, date_str, time]):
            flash("Missing required booking information.", 'danger')
            return redirect(url_for('patient_book_appointment'))

        # Check if date is in the future
        if date_str < date.today().strftime('%Y-%m-%d'):
            flash("Appointments must be booked for today or a future date.", 'danger')
            return redirect(url_for('patient_book_appointment'))
            
        if create_appointment(patient_id, doctor_id, date_str, time):
            flash("Appointment booked successfully!", 'success')
            return redirect(url_for('patient_dashboard'))
        else:
            flash("Booking failed. The doctor may no longer be available at that exact time.", 'danger')
            return redirect(url_for('patient_book_appointment'))

    # Prepare context for the template
    context = {
        'departments': departments,
        'doctors': doctors,
        'today': date.today().strftime('%Y-%m-%d'),
        'current_page': 'book_appointment' # Used for navigation/styling
    }
    return render_template('dashboards/patient_book.html', title='Book Appointment', **context)

# API Endpoint to fetch availability dynamically (AJAX/JS)
@app.route('/api/doctor/<int:doctor_id>/availability/<string:date_str>')
@login_required(role='Patient')
def api_get_availability(doctor_id, date_str):
    """API endpoint to get available slots for a doctor on a given date."""
    # Check if the date is valid and not in the past
    try:
        appt_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        if appt_date < date.today():
             return {'slots': []} # Return empty if date is in the past
    except ValueError:
        return {'error': 'Invalid date format'}, 400

    slots = get_doctor_availability_by_date(doctor_id, date_str)
    return {'slots': slots}


# --- ADMIN MANAGEMENT ROUTES ---

@app.route('/admin/doctors', methods=['GET', 'POST'])
@login_required(role='Admin')
def manage_doctors():
    """Allows Admin to view, add, or delete doctor profiles."""
    conn = get_db_connection()
    departments = get_departments()
    
    if request.method == 'POST':
        # Logic for adding a new Doctor
        username = request.form.get('username')
        password = request.form.get('password')
        name = request.form.get('name')
        contact_info = request.form.get('contact_info')
        specialization_id = request.form.get('specialization_id')

        if not all([username, password, name, specialization_id]):
            flash('All doctor fields (Name, Username, Password, Specialization) are required.', 'danger')
            return redirect(url_for('manage_doctors'))

        # 1. Create the user with role 'Doctor'
        doctor_user_id = create_user(username, password, name, contact_info, role='Doctor')

        if doctor_user_id is not None:
            # 2. Create the corresponding doctor profile
            if add_doctor_profile(doctor_user_id, specialization_id):
                flash(f"Doctor {name} added successfully! Username: {username}", 'success')
            else:
                # Cleanup user if profile creation fails (unlikely, but good practice)
                conn.execute("DELETE FROM users WHERE id = ?", (doctor_user_id,))
                conn.commit()
                flash("Failed to create doctor profile.", 'danger')
        else:
            flash('Error: Username already exists or data is invalid.', 'danger')
            
        conn.close()
        return redirect(url_for('manage_doctors'))

    # GET request: Display list of doctors and the 'Add Doctor' form
    doctors_list = conn.execute("""
        SELECT u.id, u.name, u.username, u.contact_info, d.name AS specialization
        FROM users u
        JOIN doctors doc ON u.id = doc.user_id
        JOIN departments d ON doc.specialization_id = d.id
        WHERE u.role = 'Doctor'
    """).fetchall()
    
    conn.close()
    
    context = {
        'doctors': doctors_list,
        'departments': departments
    }

    return render_template('dashboards/manage_doctors.html', title='Manage Doctors', **context)


if __name__ == '__main__':
    # You must install Flask first: pip install flask
    app.run(debug=True)