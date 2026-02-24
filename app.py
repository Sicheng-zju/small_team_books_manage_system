import os
import secrets
import mimetypes
from flask import Flask, render_template, request, redirect, url_for, send_from_directory, session, flash, jsonify

# Configure MIME type for .mjs files (crucial for PDF.js)
mimetypes.add_type('application/javascript', '.mjs')

from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)

# Configuration
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(BASE_DIR, 'library.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(BASE_DIR, 'static', 'books')
app.config['ALLOWED_EXTENSIONS'] = {'epub', 'pdf', 'txt'}

# Simple Admin Password (change 'admin123' to whatever you want)
# In production, use env vars.
ADMIN_PASSWORD_HASH = generate_password_hash('admin123')

db = SQLAlchemy(app)

# Ensure upload directory exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

class Book(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    filename = db.Column(db.String(150), unique=True, nullable=False)
    filetype = db.Column(db.String(10), nullable=False)

    def __repr__(self):
        return f'<Book {self.title}>'

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

with app.app_context():
    db.create_all()

@app.route('/')
def index():
    query = request.args.get('q')
    page = request.args.get('page', 1, type=int)
    per_page = 20  # Show 20 books per page

    if query:
        books_pagination = Book.query.filter(Book.title.contains(query)).paginate(page=page, per_page=per_page, error_out=False)
    else:
        books_pagination = Book.query.paginate(page=page, per_page=per_page, error_out=False)
    
    return render_template('index.html', books=books_pagination, query=query)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        password = request.form.get('password')
        if check_password_hash(ADMIN_PASSWORD_HASH, password):
            session['is_admin'] = True
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Incorrect password')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('is_admin', None)
    return redirect(url_for('index'))

@app.route('/admin')
def admin_dashboard():
    if not session.get('is_admin'):
        return redirect(url_for('login'))
    books = Book.query.all()
    return render_template('admin.html', books=books)

@app.route('/admin/upload', methods=['POST'])
def upload_book():
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
        
    if file and allowed_file(file.filename):
        # Use original filename as title (preserves Chinese/special chars)
        title = file.filename.rsplit('.', 1)[0]
        
        # WE ARE TRUSTING THE USER'S FILENAME HERE TO KEEP CHINESE CHARACTERS
        # BUT WE MUST STRIP PATHS TO PREVENT DIRECTORY TRAVERSAL
        filename = os.path.basename(file.filename)
        
        # Fallback if somehow empty
        if not filename:
             import uuid
             ext = file.filename.rsplit('.', 1)[1].lower()
             filename = f"{uuid.uuid4().hex}.{ext}"

        # Handle duplicates by renaming if necessary could be added here
        # For now, simplistic overwrite check or unique constraint
        if Book.query.filter_by(filename=filename).first():
             return jsonify({'error': 'File with this name already exists'}), 400

        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        filetype = file.filename.rsplit('.', 1)[1].lower()
        
        new_book = Book(title=title, filename=filename, filetype=filetype)
        db.session.add(new_book)
        db.session.commit()
        return jsonify({'success': True})
    
    return jsonify({'error': 'Invalid file type'}), 400

@app.route('/admin/delete/<int:book_id>', methods=['POST'])
def delete_book(book_id):
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    book = Book.query.get_or_404(book_id)
    try:
        os.remove(os.path.join(app.config['UPLOAD_FOLDER'], book.filename))
    except FileNotFoundError:
        pass # File might be gone already
    
    db.session.delete(book)
    db.session.commit()
    return jsonify({'success': True})

@app.route('/admin/rename/<int:book_id>', methods=['POST'])
def rename_book(book_id):
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    book = Book.query.get_or_404(book_id)
    new_title = request.form.get('title')
    if new_title:
        book.title = new_title
        db.session.commit()
        return jsonify({'success': True})
    return jsonify({'error': 'Missing title'}), 400

@app.route('/read/<int:book_id>')
def read_book(book_id):
    book = Book.query.get_or_404(book_id)
    if book.filetype == 'epub':
        return render_template('read_epub.html', book=book)
    elif book.filetype == 'pdf':
        return render_template('read_pdf.html', book=book)
    elif book.filetype == 'txt':
        return render_template('read_txt.html', book=book)
    else:
        return "Format not supported", 400

@app.route('/books/<filename>')
def serve_book(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

if __name__ == '__main__':
    # host='0.0.0.0' allows access from LAN
    app.run(host='0.0.0.0', port=5000, debug=True)
