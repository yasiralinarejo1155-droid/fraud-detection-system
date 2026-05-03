from ai_text_model import detect_ai_text_deterministic
from easypaisa_ocr_validator import validate_easypaisa_receipt
from flask import Flask, render_template, redirect, url_for, flash, request, session, jsonify, send_file
import os
import random
import io
import csv
from datetime import datetime
from functools import wraps
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from PIL import Image as PILImage
from requests_oauthlib import OAuth2Session
from dotenv import load_dotenv
from urllib.parse import quote_plus

# Load environment variables
load_dotenv()

# Allow HTTP for localhost OAuth development
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

# ============================================
# APP CONFIGURATION
# ============================================
app = Flask(__name__, static_folder='static', static_url_path='/static')
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'fraudshield-ai-secret-key-2024')
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# MySQL Database Configuration
DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_USER = os.getenv('DB_USER', 'root')
DB_PASSWORD = os.getenv('DB_PASSWORD', '')
DB_NAME = os.getenv('DB_NAME', 'fraudshield')

# URL-encode the password to safely handle special characters
ENCODED_PASSWORD = quote_plus(DB_PASSWORD) if DB_PASSWORD else ''

print(f"Connecting to MySQL: Host={DB_HOST}, User={DB_USER}, Database={DB_NAME}")

# Build connection string
app.config['SQLALCHEMY_DATABASE_URI'] = f"mysql+mysqlconnector://{DB_USER}:{ENCODED_PASSWORD}@{DB_HOST}/{DB_NAME}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['PROFILE_UPLOAD_FOLDER'] = 'static/uploads/profile_pics'
app.config['TEXT_UPLOAD_FOLDER'] = 'static/text_uploads'
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024

# Create directories
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['PROFILE_UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['TEXT_UPLOAD_FOLDER'], exist_ok=True)

# Create logo directory and placeholder
os.makedirs('static/uploads/images', exist_ok=True)

db = SQLAlchemy(app)

# ============================================
# GOOGLE OAUTH - FROM ENV VARIABLES
# ============================================
GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID')
GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET')
GOOGLE_AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v1/userinfo"
REDIRECT_URI = os.getenv('REDIRECT_URI', "http://localhost:5000/google-authorize")

# ============================================
# DATABASE MODELS
# ============================================
class User(db.Model):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    phone = db.Column(db.String(20), unique=True, nullable=True)
    password = db.Column(db.String(200), nullable=True)
    profile_image = db.Column(db.String(200), default='default.jpg')
    role = db.Column(db.String(20), default='user')
    google_id = db.Column(db.String(100), unique=True, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    transaction_images = db.relationship('TransactionImage', backref='user', lazy=True, cascade='all, delete-orphan')
    ai_images = db.relationship('AIImage', backref='user', lazy=True, cascade='all, delete-orphan')
    ai_texts = db.relationship('AIText', backref='user', lazy=True, cascade='all, delete-orphan')
    feedbacks = db.relationship('Feedback', backref='user', lazy=True, cascade='all, delete-orphan')
    reports = db.relationship('Report', backref='user', lazy=True, cascade='all, delete-orphan')

class TransactionImage(db.Model):
    __tablename__ = 'transaction_image'
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(200), nullable=False)
    original_filename = db.Column(db.String(200), nullable=False)
    real_percentage = db.Column(db.Float, default=50.0)
    fake_percentage = db.Column(db.Float, default=50.0)
    result = db.Column(db.String(20), default='PENDING')
    confidence = db.Column(db.Float, default=0.0)
    analysis_details = db.Column(db.Text, default='')
    upload_date = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

class AIImage(db.Model):
    __tablename__ = 'ai_image'
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(200), nullable=False)
    original_filename = db.Column(db.String(200), nullable=False)
    ai_probability = db.Column(db.Float, default=50.0)
    real_probability = db.Column(db.Float, default=50.0)
    result = db.Column(db.String(20), default='PENDING')
    confidence = db.Column(db.Float, default=0.0)
    analysis_details = db.Column(db.Text, default='')
    upload_date = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

class AIText(db.Model):
    __tablename__ = 'ai_text'
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    filename = db.Column(db.String(200), nullable=True)
    ai_percentage = db.Column(db.Float, default=50.0)
    human_percentage = db.Column(db.Float, default=50.0)
    result = db.Column(db.String(20), default='PENDING')
    confidence = db.Column(db.Float, default=0.0)
    analysis_details = db.Column(db.Text, default='')
    word_count = db.Column(db.Integer, default=0)
    char_count = db.Column(db.Integer, default=0)
    upload_date = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

class Feedback(db.Model):
    __tablename__ = 'feedback'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    feedback_type = db.Column(db.String(50))
    subject = db.Column(db.String(200))
    message = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Report(db.Model):
    __tablename__ = 'report'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    report_type = db.Column(db.String(50))
    item_id = db.Column(db.Integer)
    issue_description = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# ============================================
# LOGIN DECORATORS
# ============================================
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login first', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session or session.get('role') != 'admin':
            flash('Admin access required', 'danger')
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

# ============================================
# GOOGLE OAUTH ROUTES
# ============================================
@app.route('/google-login')
def google_login():
    try:
        oauth = OAuth2Session(
            GOOGLE_CLIENT_ID,
            redirect_uri=REDIRECT_URI,
            scope=['openid', 'email', 'profile']
        )
        authorization_url, state = oauth.authorization_url(
            GOOGLE_AUTHORIZATION_URL,
            access_type='online',
            prompt='select_account'
        )
        session['oauth_state'] = state
        return redirect(authorization_url)
    except Exception as e:
        print(f"Google login error: {str(e)}")
        flash('Google login temporarily unavailable', 'warning')
        return redirect(url_for('login'))

@app.route('/google-authorize')
def google_authorize():
    try:
        state = session.get('oauth_state')
        if not state:
            flash('Session expired. Please try again.', 'warning')
            return redirect(url_for('login'))
        
        oauth = OAuth2Session(
            GOOGLE_CLIENT_ID,
            state=state,
            redirect_uri=REDIRECT_URI
        )
        
        token = oauth.fetch_token(
            GOOGLE_TOKEN_URL,
            client_secret=GOOGLE_CLIENT_SECRET,
            authorization_response=request.url
        )
        
        userinfo_response = oauth.get(GOOGLE_USERINFO_URL)
        user_info = userinfo_response.json()
        
        email = user_info.get('email')
        name = user_info.get('name', email.split('@')[0] if email else 'user')
        google_id = user_info.get('id')
        
        if not email:
            flash('Could not retrieve email from Google', 'danger')
            return redirect(url_for('login'))
        
        user = User.query.filter_by(email=email).first()
        
        if user:
            session['user_id'] = user.id
            session['username'] = user.username
            session['email'] = user.email
            session['role'] = user.role
            session['logged_in'] = True
            flash(f'Welcome back, {user.username}!', 'success')
        else:
            username = name.lower().replace(' ', '_')
            username = ''.join(c for c in username if c.isalnum() or c == '_')
            
            counter = 1
            original_username = username
            while User.query.filter_by(username=username).first():
                username = f"{original_username}{counter}"
                counter += 1
            
            new_user = User(
                username=username,
                email=email,
                phone=None,
                password=None,
                google_id=google_id,
                role='user',
                profile_image='default.jpg'
            )
            db.session.add(new_user)
            db.session.commit()
            
            session['user_id'] = new_user.id
            session['username'] = new_user.username
            session['email'] = new_user.email
            session['role'] = new_user.role
            session['logged_in'] = True
            flash(f'Welcome to FraudShield AI, {username}!', 'success')
        
        return redirect(url_for('user_dashboard'))
        
    except Exception as e:
        print(f"Google OAuth error: {str(e)}")
        flash('Google login failed. Please try again.', 'danger')
        return redirect(url_for('login'))

# ============================================
# AI DETECTION FUNCTIONS
# ============================================
def detect_fake_transaction(image_path):
    """
    Detect fake transaction receipt using OCR + Rule-based validation
    """
    try:
        # Use EasyPaisa validator
        result = validate_easypaisa_receipt(image_path)
        
        # Map result to expected format
        if result['result'] == 'REAL':
            real_percentage = result['confidence']
            fake_percentage = 100 - real_percentage
            final_result = "REAL"
        elif result['result'] == 'LIKELY REAL':
            real_percentage = result['confidence']
            fake_percentage = 100 - real_percentage
            final_result = "LIKELY REAL"
        elif result['result'] == 'UNCERTAIN':
            real_percentage = 50
            fake_percentage = 50
            final_result = "UNCERTAIN"
        elif result['result'] == 'FAKE':
            real_percentage = 100 - result['confidence']
            fake_percentage = result['confidence']
            final_result = "FAKE"
        else:
            real_percentage = 50
            fake_percentage = 50
            final_result = "UNCERTAIN"
        
        return {
            'real_percentage': round(real_percentage, 2),
            'fake_percentage': round(fake_percentage, 2),
            'result': final_result,
            'confidence': round(result['confidence'], 2),
            'analysis_details': result['analysis_details']
        }
        
    except Exception as e:
        print(f"Error in detect_fake_transaction: {e}")
        return {
            'real_percentage': 50.0,
            'fake_percentage': 50.0,
            'result': "ERROR",
            'confidence': 0.0,
            'analysis_details': f"Error: {str(e)}"
        }

def detect_ai_text(text_content):
    """
    DETERMINISTIC AI Text Detection
    Same input → SAME output every time (NO randomness)
    """
    try:
        # Use the deterministic detector
        result = detect_ai_text_deterministic(text_content)
        
        return {
            'ai_percentage': result['ai_percentage'],
            'human_percentage': result['human_percentage'],
            'result': result['result'],
            'confidence': result['confidence'],
            'analysis_details': result['analysis_details'],
            'word_count': result['word_count'],
            'char_count': result['char_count']
        }
    except Exception as e:
        print(f"Error in deterministic detection: {e}")
        # Fallback - still deterministic
        words = text_content.split()
        word_count = len(words)
        
        if word_count < 50:
            return {
                'ai_percentage': 0.0,
                'human_percentage': 0.0,
                'result': 'INSUFFICIENT TEXT',
                'confidence': 0.0,
                'analysis_details': f'Please provide more text. Current word count: {word_count}',
                'word_count': word_count,
                'char_count': len(text_content)
            }
        
        # Deterministic fallback based on text length and complexity
        unique_ratio = len(set(w.lower() for w in words)) / word_count if word_count > 0 else 0
        avg_word_len = sum(len(w) for w in words) / word_count if word_count > 0 else 0
        
        # Fixed formula - NO randomness
        if unique_ratio < 0.4 and avg_word_len > 6:
            ai_pct = 75.0
            human_pct = 25.0
            result = "LIKELY AI"
        elif unique_ratio > 0.6 and avg_word_len < 5:
            ai_pct = 25.0
            human_pct = 75.0
            result = "LIKELY HUMAN"
        else:
            ai_pct = 50.0
            human_pct = 50.0
            result = "UNCERTAIN"
        
        return {
            'ai_percentage': ai_pct,
            'human_percentage': human_pct,
            'result': result,
            'confidence': max(ai_pct, human_pct),
            'analysis_details': f"Analysis based on {word_count} words. Unique word ratio: {unique_ratio:.1%}",
            'word_count': word_count,
            'char_count': len(text_content)
        }

# ============================================
# MAIN ROUTES
# ============================================
@app.route('/')
def home():
    return render_template('home.html')

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/contact')
def contact():
    return render_template('contact.html')

# ============================================
# AUTH ROUTES
# ============================================
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        phone = request.form.get('phone')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        if not all([username, email, phone, password, confirm_password]):
            flash('All fields are required', 'danger')
            return redirect(url_for('signup'))
        
        if password != confirm_password:
            flash('Passwords do not match', 'danger')
            return redirect(url_for('signup'))
        
        existing = User.query.filter(
            (User.username == username) | (User.email == email) | (User.phone == phone)
        ).first()
        
        if existing:
            flash('Username/Email/Phone already exists', 'danger')
            return redirect(url_for('signup'))
        
        hashed = generate_password_hash(password)
        new_user = User(
            username=username,
            email=email,
            phone=phone,
            password=hashed,
            role='user'
        )
        
        # Handle profile picture upload
        if 'profile_pic' in request.files:
            file = request.files['profile_pic']
            if file and file.filename:
                filename = secure_filename(f"user_{new_user.id}_{file.filename}")
                file.save(os.path.join(app.config['PROFILE_UPLOAD_FOLDER'], filename))
                new_user.profile_image = filename
        
        db.session.add(new_user)
        db.session.commit()
        
        flash('Account created successfully! Please login.', 'success')
        return redirect(url_for('login'))
    
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        identifier = request.form.get('identifier')
        password = request.form.get('password')
        
        user = User.query.filter(
            (User.username == identifier) | (User.email == identifier) | (User.phone == identifier)
        ).first()
        
        if user and user.password and check_password_hash(user.password, password):
            session['user_id'] = user.id
            session['username'] = user.username
            session['email'] = user.email
            session['role'] = user.role
            session['logged_in'] = True
            
            flash(f'Welcome back, {user.username}!', 'success')
            
            if user.role == 'admin':
                return redirect(url_for('admin_dashboard'))
            return redirect(url_for('user_dashboard'))
        else:
            flash('Invalid credentials!', 'danger')
    
    return render_template('login.html')

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        identifier = request.form.get('identifier')
        password = request.form.get('password')
        
        user = User.query.filter(
            (User.username == identifier) | (User.email == identifier) | (User.phone == identifier)
        ).first()
        
        if user and user.role == 'admin' and user.password and check_password_hash(user.password, password):
            session['user_id'] = user.id
            session['username'] = user.username
            session['email'] = user.email
            session['role'] = user.role
            session['logged_in'] = True
            
            flash('Admin login successful!', 'success')
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Invalid admin credentials!', 'danger')
    
    return render_template('admin_login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully', 'info')
    return redirect(url_for('home'))

# ============================================
# USER DASHBOARD
# ============================================
@app.route('/user/dashboard')
@login_required
def user_dashboard():
    user_id = session['user_id']
    username = session['username']
    
    transactions = TransactionImage.query.filter_by(user_id=user_id).order_by(TransactionImage.upload_date.desc()).all()
    ai_images = AIImage.query.filter_by(user_id=user_id).order_by(AIImage.upload_date.desc()).all()
    ai_texts = AIText.query.filter_by(user_id=user_id).order_by(AIText.upload_date.desc()).all()
    
    all_items = []
    for item in transactions:
        item.type = 'transaction'
        all_items.append(item)
    for item in ai_images:
        item.type = 'ai_image'
        all_items.append(item)
    for item in ai_texts:
        item.type = 'ai_text'
        all_items.append(item)
    
    all_items.sort(key=lambda x: x.upload_date, reverse=True)
    
    total_items = len(all_items)
    real_count = sum(1 for i in all_items if i.result in ['REAL', 'REAL PHOTO', 'HUMAN WRITTEN', 'LIKELY REAL', 'LIKELY HUMAN'])
    fake_count = sum(1 for i in all_items if i.result in ['FAKE', 'AI GENERATED', 'AI WRITTEN', 'LIKELY FAKE', 'LIKELY AI'])
    uncertain_count = total_items - real_count - fake_count
    
    return render_template('user_dashboard.html',
                         username=username,
                         items=all_items,
                         total_items=total_items,
                         real_count=real_count,
                         fake_count=fake_count,
                         uncertain_count=uncertain_count)

@app.route('/my-account')
@login_required
def my_account():
    user = User.query.get(session['user_id'])
    total_scans = len(user.transaction_images) + len(user.ai_images) + len(user.ai_texts)
    real_count = sum(1 for i in user.transaction_images if i.result in ['REAL', 'LIKELY REAL'])
    real_count += sum(1 for i in user.ai_images if i.result in ['REAL PHOTO', 'LIKELY REAL'])
    real_count += sum(1 for i in user.ai_texts if i.result in ['HUMAN WRITTEN', 'LIKELY HUMAN'])
    fake_count = total_scans - real_count
    return render_template('my_account.html', user=user, total_scans=total_scans, real_count=real_count, fake_count=fake_count)

@app.route('/update-account', methods=['POST'])
@login_required
def update_account():
    user = User.query.get(session['user_id'])
    
    username = request.form.get('username')
    email = request.form.get('email')
    phone = request.form.get('phone')
    
    if username:
        user.username = username
    if email:
        user.email = email
    if phone:
        user.phone = phone
    
    db.session.commit()
    session['username'] = user.username
    session['email'] = user.email
    
    flash('Profile updated successfully!', 'success')
    return redirect(url_for('my_account'))

# ============================================
# UPLOAD ROUTES
# ============================================
@app.route('/transaction/upload', methods=['GET', 'POST'])
@login_required
def transaction_upload():
    if request.method == 'POST':
        if 'image' not in request.files:
            flash('No file selected', 'danger')
            return redirect(request.url)
        
        file = request.files['image']
        if file.filename == '':
            flash('No file selected', 'danger')
            return redirect(request.url)
        
        try:
            filename = secure_filename(file.filename)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            new_filename = f"transaction_{timestamp}_{filename}"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], new_filename)
            file.save(filepath)
            
            analysis = detect_fake_transaction(filepath)
            
            new_image = TransactionImage(
                filename=new_filename,
                original_filename=filename,
                real_percentage=analysis['real_percentage'],
                fake_percentage=analysis['fake_percentage'],
                result=analysis['result'],
                confidence=analysis['confidence'],
                analysis_details=analysis['analysis_details'],
                user_id=session['user_id']
            )
            db.session.add(new_image)
            db.session.commit()
            
            flash(f'Analysis complete! Result: {analysis["result"]}', 'success')
            return redirect(url_for('transaction_result', image_id=new_image.id))
        except Exception as e:
            flash(f'Error: {str(e)}', 'danger')
            return redirect(request.url)
    
    return render_template('transaction_upload.html')

@app.route('/transaction/result/<int:image_id>')
@login_required
def transaction_result(image_id):
    image = TransactionImage.query.get_or_404(image_id)
    if image.user_id != session['user_id'] and session.get('role') != 'admin':
        flash('Access denied', 'danger')
        return redirect(url_for('user_dashboard'))
    return render_template('transaction_result.html', image=image)

@app.route('/ai-image/upload', methods=['GET', 'POST'])
@login_required
def ai_image_upload():
    if request.method == 'POST':
        if 'image' not in request.files:
            flash('No file selected', 'danger')
            return redirect(request.url)
        
        file = request.files['image']
        if file.filename == '':
            flash('No file selected', 'danger')
            return redirect(request.url)
        
        try:
            filename = secure_filename(file.filename)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            new_filename = f"ai_image_{timestamp}_{filename}"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], new_filename)
            file.save(filepath)
            
            analysis = detect_ai_image(filepath)
            
            new_image = AIImage(
                filename=new_filename,
                original_filename=filename,
                ai_probability=analysis['ai_probability'],
                real_probability=analysis['real_probability'],
                result=analysis['result'],
                confidence=analysis['confidence'],
                analysis_details=analysis['analysis_details'],
                user_id=session['user_id']
            )
            db.session.add(new_image)
            db.session.commit()
            
            flash(f'Analysis complete! Result: {analysis["result"]}', 'success')
            return redirect(url_for('ai_image_result', image_id=new_image.id))
        except Exception as e:
            flash(f'Error: {str(e)}', 'danger')
            return redirect(request.url)
    
    return render_template('ai_image_upload.html')

@app.route('/ai-image/result/<int:image_id>')
@login_required
def ai_image_result(image_id):
    image = AIImage.query.get_or_404(image_id)
    if image.user_id != session['user_id'] and session.get('role') != 'admin':
        flash('Access denied', 'danger')
        return redirect(url_for('user_dashboard'))
    return render_template('ai_image_result.html', image=image)

@app.route('/ai-text/detect', methods=['GET', 'POST'])
@login_required
def ai_text_detect():
    if request.method == 'POST':
        text_content = request.form.get('text_content', '')
        
        if not text_content:
            flash('Please enter some text', 'danger')
            return redirect(request.url)
        
        analysis = detect_ai_text(text_content)
        
        new_text = AIText(
            content=text_content[:5000],
            ai_percentage=analysis['ai_percentage'],
            human_percentage=analysis['human_percentage'],
            result=analysis['result'],
            confidence=analysis['confidence'],
            analysis_details=analysis['analysis_details'],
            word_count=analysis['word_count'],
            char_count=analysis['char_count'],
            user_id=session['user_id']
        )
        db.session.add(new_text)
        db.session.commit()
        
        flash(f'Analysis complete! Result: {analysis["result"]}', 'success')
        return redirect(url_for('ai_text_result', text_id=new_text.id))
    
    return render_template('ai_text_detect.html')

@app.route('/ai-text/result/<int:text_id>')
@login_required
def ai_text_result(text_id):
    text = AIText.query.get_or_404(text_id)
    if text.user_id != session['user_id'] and session.get('role') != 'admin':
        flash('Access denied', 'danger')
        return redirect(url_for('user_dashboard'))
    return render_template('ai_text_result.html', text=text)

# ============================================
# DELETE ROUTES
# ============================================
@app.route('/delete-transaction/<int:image_id>', methods=['POST'])
@login_required
def delete_transaction(image_id):
    try:
        image = TransactionImage.query.get_or_404(image_id)
        if image.user_id != session['user_id']:
            return jsonify({'success': False, 'message': 'Access denied'}), 403
        db.session.delete(image)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Deleted'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/delete-ai-image/<int:image_id>', methods=['POST'])
@login_required
def delete_ai_image(image_id):
    try:
        image = AIImage.query.get_or_404(image_id)
        if image.user_id != session['user_id']:
            return jsonify({'success': False, 'message': 'Access denied'}), 403
        db.session.delete(image)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Deleted'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/delete-ai-text/<int:text_id>', methods=['POST'])
@login_required
def delete_ai_text(text_id):
    try:
        text = AIText.query.get_or_404(text_id)
        if text.user_id != session['user_id']:
            return jsonify({'success': False, 'message': 'Access denied'}), 403
        db.session.delete(text)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Deleted'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

# ============================================
# FEEDBACK ROUTES
# ============================================
@app.route('/submit-feedback', methods=['POST'])
@login_required
def submit_feedback():
    try:
        data = request.get_json()
        feedback = Feedback(
            user_id=session['user_id'],
            feedback_type=data.get('type', 'general'),
            subject=data.get('subject', ''),
            message=data.get('message', ''),
            status='pending'
        )
        db.session.add(feedback)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Feedback submitted'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/submit-report', methods=['POST'])
@login_required
def submit_report():
    try:
        data = request.get_json()
        report = Report(
            user_id=session['user_id'],
            report_type=data.get('report_type'),
            item_id=data.get('item_id'),
            issue_description=data.get('issue_description'),
            status='pending'
        )
        db.session.add(report)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Report submitted'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

# ============================================
# ADMIN ROUTES
# ============================================
@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    try:
        users = User.query.all()
        transactions = TransactionImage.query.all()
        ai_images = AIImage.query.all()
        ai_texts = AIText.query.all()
        
        pending_feedback = Feedback.query.filter_by(status='pending').count()
        pending_reports = Report.query.filter_by(status='pending').count()
        
        feedbacks = Feedback.query.order_by(Feedback.created_at.desc()).limit(10).all()
        reports = Report.query.order_by(Report.created_at.desc()).limit(10).all()
        
        activities = []
        
        stats = {
            'total_users': len(users),
            'total_transactions': len(transactions),
            'total_ai_images': len(ai_images),
            'total_ai_texts': len(ai_texts),
            'fraud_transactions': sum(1 for t in transactions if t.result in ['FAKE', 'LIKELY FAKE']),
            'ai_generated_images': sum(1 for i in ai_images if i.result in ['AI GENERATED', 'LIKELY AI']),
            'ai_generated_texts': sum(1 for t in ai_texts if t.result in ['AI WRITTEN', 'LIKELY AI']),
            'total_scans': len(transactions) + len(ai_images) + len(ai_texts)
        }
        
        return render_template('admin_dashboard.html',
                             admin_name=session.get('username', 'Admin'),
                             stats=stats,
                             users=users[:10],
                             activities=activities,
                             feedbacks=feedbacks,
                             reports=reports,
                             pending_feedback=pending_feedback,
                             pending_reports=pending_reports,
                             now=datetime.now())
    except Exception as e:
        print(f"Admin dashboard error: {str(e)}")
        flash(f'Error loading dashboard: {str(e)}', 'danger')
        return redirect(url_for('home'))

@app.route('/admin/users')
@admin_required
def admin_users():
    users = User.query.all()
    return render_template('admin_users.html', users=users)

@app.route('/admin/transactions')
@admin_required
def admin_transactions():
    transactions = TransactionImage.query.all()
    return render_template('admin_transactions.html', transactions=transactions)

@app.route('/admin/ai-images')
@admin_required
def admin_ai_images():
    images = AIImage.query.all()
    return render_template('admin_ai_images.html', images=images)

@app.route('/admin/ai-texts')
@admin_required
def admin_ai_texts():
    texts = AIText.query.all()
    return render_template('admin_ai_texts.html', ai_texts=texts)

@app.route('/admin/feedback')
@admin_required
def admin_feedback():
    feedbacks = Feedback.query.all()
    reports = Report.query.all()
    return render_template('admin_feedback.html', feedbacks=feedbacks, reports=reports)

@app.route('/admin/user/<int:user_id>')
@admin_required
def admin_user_detail(user_id):
    user = User.query.get_or_404(user_id)
    transactions = TransactionImage.query.filter_by(user_id=user_id).all()
    ai_texts = AIText.query.filter_by(user_id=user_id).all()
    return render_template('admin_user_detail.html', user=user, transactions=transactions, ai_texts=ai_texts)

@app.route('/admin/update-feedback/<int:feedback_id>', methods=['POST'])
@admin_required
def update_feedback(feedback_id):
    try:
        feedback = Feedback.query.get_or_404(feedback_id)
        data = request.get_json()
        feedback.status = data.get('status', 'resolved')
        db.session.commit()
        return jsonify({'success': True, 'message': 'Feedback updated'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/admin/update-report/<int:report_id>', methods=['POST'])
@admin_required
def update_report(report_id):
    try:
        report = Report.query.get_or_404(report_id)
        data = request.get_json()
        report.status = data.get('status', 'resolved')
        db.session.commit()
        return jsonify({'success': True, 'message': 'Report updated'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/admin/delete-user/<int:user_id>', methods=['POST'])
@admin_required
def delete_user(user_id):
    try:
        user = User.query.get_or_404(user_id)
        if user.id == session['user_id']:
            return jsonify({'success': False, 'message': 'Cannot delete yourself'})
        db.session.delete(user)
        db.session.commit()
        return jsonify({'success': True, 'message': 'User deleted'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/admin/export-stats')
@admin_required
def export_stats():
    output = io.StringIO()
    writer = csv.writer(output)
    
    writer.writerow(['FraudShield AI Statistics'])
    writer.writerow(['Generated:', datetime.now().strftime('%Y-%m-%d %H:%M:%S')])
    writer.writerow([])
    
    total_users = User.query.count()
    writer.writerow(['Total Users', total_users])
    
    total_transactions = TransactionImage.query.count()
    real_transactions = TransactionImage.query.filter(TransactionImage.result.in_(['REAL', 'LIKELY REAL'])).count()
    fake_transactions = TransactionImage.query.filter(TransactionImage.result.in_(['FAKE', 'LIKELY FAKE'])).count()
    writer.writerow(['Transaction Scans', total_transactions])
    writer.writerow([' - Real Transactions', real_transactions])
    writer.writerow([' - Fake Transactions', fake_transactions])
    
    total_ai_images = AIImage.query.count()
    ai_generated = AIImage.query.filter(AIImage.result.in_(['AI GENERATED', 'LIKELY AI'])).count()
    real_photos = AIImage.query.filter(AIImage.result.in_(['REAL PHOTO', 'LIKELY REAL'])).count()
    writer.writerow(['AI Image Scans', total_ai_images])
    writer.writerow([' - AI Generated', ai_generated])
    writer.writerow([' - Real Photos', real_photos])
    
    total_ai_texts = AIText.query.count()
    ai_written = AIText.query.filter(AIText.result.in_(['AI WRITTEN', 'LIKELY AI'])).count()
    human_written = AIText.query.filter(AIText.result.in_(['HUMAN WRITTEN', 'LIKELY HUMAN'])).count()
    writer.writerow(['AI Text Scans', total_ai_texts])
    writer.writerow([' - AI Written', ai_written])
    writer.writerow([' - Human Written', human_written])
    
    writer.writerow([])
    writer.writerow(['Total Scans', total_transactions + total_ai_images + total_ai_texts])
    
    output.seek(0)
    
    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'fraudshield_stats_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    )

# ============================================
# API ROUTES FOR SAVING ANALYSIS RESULTS
# ============================================
@app.route('/transaction/upload-api', methods=['POST'])
@login_required
def transaction_upload_api():
    try:
        data = request.get_json()
        new_image = TransactionImage(
            filename=data.get('filename', 'unknown'),
            original_filename=data.get('original_filename', 'unknown'),
            real_percentage=data.get('real_percentage', 50),
            fake_percentage=data.get('fake_percentage', 50),
            result=data.get('result', 'PENDING'),
            confidence=data.get('confidence', 0),
            analysis_details=data.get('analysis_details', ''),
            user_id=session['user_id']
        )
        db.session.add(new_image)
        db.session.commit()
        return jsonify({'success': True, 'id': new_image.id})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/ai-text/detect-api', methods=['POST'])
@login_required
def ai_text_detect_api():
    try:
        data = request.get_json()
        new_text = AIText(
            content=data.get('content', ''),
            filename=data.get('filename', ''),
            ai_percentage=data.get('ai_percentage', 50),
            human_percentage=data.get('human_percentage', 50),
            result=data.get('result', 'PENDING'),
            confidence=data.get('confidence', 0),
            analysis_details=data.get('analysis_details', ''),
            word_count=data.get('word_count', 0),
            char_count=data.get('char_count', 0),
            user_id=session['user_id']
        )
        db.session.add(new_text)
        db.session.commit()
        return jsonify({'success': True, 'id': new_text.id})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/get-unread-counts')
@admin_required
def get_unread_counts():
    try:
        pending_feedback = Feedback.query.filter_by(status='pending').count()
        pending_reports = Report.query.filter_by(status='pending').count()
        return jsonify({
            'success': True,
            'feedback_count': pending_feedback,
            'report_count': pending_reports,
            'total': pending_feedback + pending_reports
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

# ============================================
# RESOURCE ROUTES
# ============================================
@app.route('/documentation')
def documentation():
    return render_template('documentation.html')

@app.route('/blogs')
def blogs():
    return render_template('blogs.html')

@app.route('/case-studies')
def case_studies():
    return render_template('case_studies.html')

@app.route('/research-papers')
def research_papers():
    return render_template('research_papers.html')

@app.route('/blog/<slug>')
def blog_post(slug):
    class BlogPost:
        pass
    
    post = BlogPost()
    post.title = 'Blog Post'
    post.category = 'Fraud Detection'
    post.date = 'March 2026'
    post.author = 'FraudShield Team'
    post.read_time = '8 min read'
    post.image = 'fa-shield-halved'
    post.content = f"<h2>Blog Post</h2><p>Content for {slug}</p>"
    
    return render_template('blog_post.html', post=post, slug=slug)

@app.route('/my-scans')
@login_required
def my_scans():
    scan_type = request.args.get('scan_type', 'all')
    user_id = session['user_id']
    
    if scan_type == 'transaction' or scan_type == 'all':
        transactions = TransactionImage.query.filter_by(user_id=user_id).order_by(TransactionImage.upload_date.desc()).all()
    else:
        transactions = []
    
    if scan_type == 'ai_image' or scan_type == 'all':
        ai_images = AIImage.query.filter_by(user_id=user_id).order_by(AIImage.upload_date.desc()).all()
    else:
        ai_images = []
    
    if scan_type == 'ai_text' or scan_type == 'all':
        ai_texts = AIText.query.filter_by(user_id=user_id).order_by(AIText.upload_date.desc()).all()
    else:
        ai_texts = []
    
    all_items = []
    for item in transactions:
        item.type = 'transaction'
        all_items.append(item)
    for item in ai_images:
        item.type = 'ai_image'
        all_items.append(item)
    for item in ai_texts:
        item.type = 'ai_text'
        all_items.append(item)
    
    all_items.sort(key=lambda x: x.upload_date, reverse=True)
    
    return render_template('my_scans.html', 
                         items=all_items, 
                         scan_type=scan_type,
                         total_items=len(all_items))

# ============================================
# DATABASE INIT
# ============================================
def init_db():
    with app.app_context():
        try:
            from sqlalchemy import text
            engine = db.engine
            
            print("Creating/Resetting database...")
            with engine.connect() as connection:
                connection.execute(text("SET FOREIGN_KEY_CHECKS = 0;"))
                db.metadata.drop_all(bind=engine)
                db.metadata.create_all(bind=engine)
                connection.execute(text("SET FOREIGN_KEY_CHECKS = 1;"))
                connection.commit()
            
            print("✅ MySQL Database created/reset successfully!")
            
            # Create default admin user
            if not User.query.filter_by(role='admin').first():
                admin = User(
                    username='admin',
                    email='admin@fraudshield.com',
                    phone='+1234567890',
                    password=generate_password_hash('Admin@123'),
                    role='admin'
                )
                db.session.add(admin)
            
            # Create test user
            if not User.query.filter_by(username='testuser').first():
                test = User(
                    username='testuser',
                    email='user@test.com',
                    phone='+0987654321',
                    password=generate_password_hash('User@123'),
                    role='user'
                )
                db.session.add(test)
            
            db.session.commit()
            
            # Create default profile image
            from PIL import Image
            default_img_path = os.path.join(app.config['PROFILE_UPLOAD_FOLDER'], 'default.jpg')
            if not os.path.exists(default_img_path):
                img = Image.new('RGB', (200, 200), color=(44, 98, 128))
                img.save(default_img_path)
            
            print("="*50)
            print("✅ DATABASE READY!")
            print("👤 USER: user@test.com / User@123")
            print("👑 ADMIN: admin@fraudshield.com / Admin@123")
            print("="*50)
        except Exception as e:
            print(f"❌ Database Init Error: {str(e)}")

if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5000)