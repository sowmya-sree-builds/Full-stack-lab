from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
import hashlib
import secrets
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)
CORS(app, resources={r"/*": {"origins": "*"}})

# In-memory token storage
active_tokens = {}

# ==================== DATABASE SETUP ====================

def get_db():
    conn = sqlite3.connect('bookexchange.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = sqlite3.connect('bookexchange.db')
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        profile_photo TEXT DEFAULT 'https://ui-avatars.com/api/?name=User&background=667eea&color=fff',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS books (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        author TEXT NOT NULL,
        cover_url TEXT,
        description TEXT,
        isbn TEXT,
        rating REAL DEFAULT 0,
        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users (id)
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS favorites (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        book_title TEXT NOT NULL,
        book_author TEXT NOT NULL,
        book_cover TEXT,
        book_description TEXT,
        book_isbn TEXT,
        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users (id)
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS exchange_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        requester_id INTEGER NOT NULL,
        owner_id INTEGER NOT NULL,
        book_id INTEGER NOT NULL,
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (requester_id) REFERENCES users (id),
        FOREIGN KEY (owner_id) REFERENCES users (id),
        FOREIGN KEY (book_id) REFERENCES books (id)
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS completed_exchanges (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user1_id INTEGER NOT NULL,
        user2_id INTEGER NOT NULL,
        book_id INTEGER NOT NULL,
        completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user1_id) REFERENCES users (id),
        FOREIGN KEY (user2_id) REFERENCES users (id),
        FOREIGN KEY (book_id) REFERENCES books (id)
    )''')
    
    conn.commit()
    conn.close()
    print("✅ Database initialized successfully!")

# ==================== UTILITY FUNCTIONS ====================

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def generate_token():
    return secrets.token_urlsafe(32)

def get_user_from_token(token):
    if not token:
        return None
    user_data = active_tokens.get(token)
    if not user_data:
        return None
    if datetime.now() > user_data['expires']:
        del active_tokens[token]
        return None
    return user_data['user_id']

def require_auth(f):
    def wrapper(*args, **kwargs):
        token = request.headers.get('Authorization')
        if token and token.startswith('Bearer '):
            token = token[7:]
        
        user_id = get_user_from_token(token)
        if not user_id:
            return jsonify({'error': 'Authentication required'}), 401
        
        request.user_id = user_id
        return f(*args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper

# ==================== AUTHENTICATION ROUTES ====================

@app.route('/signup', methods=['POST'])
def signup():
    data = request.json
    username = data.get('username', '').strip()
    email = data.get('email', '').strip()
    password = data.get('password', '')
    
    if not all([username, email, password]):
        return jsonify({'error': 'All fields are required'}), 400
    
    if len(password) < 6:
        return jsonify({'error': 'Password must be at least 6 characters'}), 400
    
    try:
        conn = get_db()
        c = conn.cursor()
        
        profile_photo = f"https://ui-avatars.com/api/?name={username}&background=667eea&color=fff&size=200"
        
        c.execute('INSERT INTO users (username, email, password_hash, profile_photo) VALUES (?, ?, ?, ?)',
                  (username, email, hash_password(password), profile_photo))
        conn.commit()
        user_id = c.lastrowid
        conn.close()
        
        token = generate_token()
        active_tokens[token] = {
            'user_id': user_id,
            'username': username,
            'expires': datetime.now() + timedelta(hours=24)
        }
        
        return jsonify({
            'message': 'Signup successful',
            'username': username,
            'user_id': user_id,
            'token': token,
            'profile_photo': profile_photo
        }), 201
    except sqlite3.IntegrityError:
        return jsonify({'error': 'Username or email already exists'}), 409
    except Exception as e:
        return jsonify({'error': f'Server error: {str(e)}'}), 500

@app.route('/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username', '').strip()
    password = data.get('password', '')
    
    if not all([username, password]):
        return jsonify({'error': 'Username and password required'}), 400
    
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT id, username, password_hash, profile_photo FROM users WHERE username = ?', (username,))
        user = c.fetchone()
        conn.close()
        
        if user and user['password_hash'] == hash_password(password):
            token = generate_token()
            active_tokens[token] = {
                'user_id': user['id'],
                'username': user['username'],
                'expires': datetime.now() + timedelta(hours=24)
            }
            
            return jsonify({
                'message': 'Login successful',
                'username': user['username'],
                'user_id': user['id'],
                'token': token,
                'profile_photo': user['profile_photo']
            }), 200
        
        return jsonify({'error': 'Invalid username or password'}), 401
    except Exception as e:
        return jsonify({'error': f'Server error: {str(e)}'}), 500

@app.route('/logout', methods=['POST'])
def logout():
    token = request.headers.get('Authorization')
    if token and token.startswith('Bearer '):
        token = token[7:]
        if token in active_tokens:
            del active_tokens[token]
    return jsonify({'message': 'Logged out successfully'}), 200

# ==================== PROFILE ROUTES ====================

@app.route('/profile', methods=['GET'])
@require_auth
def get_profile():
    try:
        conn = get_db()
        c = conn.cursor()
        
        # Get user info
        c.execute('SELECT username, profile_photo, created_at FROM users WHERE id = ?', (request.user_id,))
        user = c.fetchone()
        
        # Count exchanges (completed)
        c.execute('SELECT COUNT(*) as count FROM completed_exchanges WHERE user1_id = ? OR user2_id = ?',
                  (request.user_id, request.user_id))
        exchanges_count = c.fetchone()['count']
        
        # Count pending requests (both sent and received)
        c.execute('''SELECT COUNT(*) as count FROM exchange_requests 
                     WHERE (requester_id = ? OR owner_id = ?) AND status = 'pending' ''',
                  (request.user_id, request.user_id))
        requests_count = c.fetchone()['count']
        
        # Count favorites
        c.execute('SELECT COUNT(*) as count FROM favorites WHERE user_id = ?', (request.user_id,))
        favorites_count = c.fetchone()['count']
        
        # Count books owned
        c.execute('SELECT COUNT(*) as count FROM books WHERE user_id = ?', (request.user_id,))
        books_count = c.fetchone()['count']
        
        conn.close()
        
        return jsonify({
            'username': user['username'],
            'profile_photo': user['profile_photo'],
            'member_since': user['created_at'],
            'stats': {
                'exchanges': exchanges_count,
                'requests': requests_count,
                'favorites': favorites_count,
                'books_owned': books_count
            }
        }), 200
    except Exception as e:
        return jsonify({'error': f'Failed to fetch profile: {str(e)}'}), 500

# ==================== BOOK SEARCH ROUTES ====================

@app.route('/search', methods=['GET'])
def search_books():
    query = request.args.get('q', '').strip().lower()
    
    if not query:
        return jsonify({'error': 'Search query required'}), 400
    
    # Enhanced mock data with more books
    all_books = [
        {
            'id': 'book1',
            'title': 'Harry Potter and the Philosopher\'s Stone',
            'author': 'J.K. Rowling',
            'cover': 'https://covers.openlibrary.org/b/id/10521270-L.jpg',
            'description': 'The first novel in the Harry Potter series and Rowling\'s debut novel.',
            'isbn': '9780439708180',
            'rating': 4.8
        },
        {
            'id': 'book2',
            'title': 'To Kill a Mockingbird',
            'author': 'Harper Lee',
            'cover': 'https://covers.openlibrary.org/b/id/8231346-L.jpg',
            'description': 'A gripping story of racial injustice and childhood innocence.',
            'isbn': '9780061120084',
            'rating': 4.7
        },
        {
            'id': 'book3',
            'title': '1984',
            'author': 'George Orwell',
            'cover': 'https://covers.openlibrary.org/b/id/7222246-L.jpg',
            'description': 'A dystopian social science fiction novel and cautionary tale.',
            'isbn': '9780451524935',
            'rating': 4.6
        },
        {
            'id': 'book4',
            'title': 'Pride and Prejudice',
            'author': 'Jane Austen',
            'cover': 'https://covers.openlibrary.org/b/id/8913952-L.jpg',
            'description': 'A romantic novel of manners set in Georgian England.',
            'isbn': '9780141439518',
            'rating': 4.5
        },
        {
            'id': 'book5',
            'title': 'The Great Gatsby',
            'author': 'F. Scott Fitzgerald',
            'cover': 'https://covers.openlibrary.org/b/id/7984916-L.jpg',
            'description': 'A story of decadence and excess in the Jazz Age.',
            'isbn': '9780743273565',
            'rating': 4.4
        },
        {
            'id': 'book6',
            'title': 'The Hobbit',
            'author': 'J.R.R. Tolkien',
            'cover': 'https://covers.openlibrary.org/b/id/8467493-L.jpg',
            'description': 'A fantasy novel about the adventures of Bilbo Baggins.',
            'isbn': '9780547928227',
            'rating': 4.7
        },
        {
            'id': 'book7',
            'title': 'The Catcher in the Rye',
            'author': 'J.D. Salinger',
            'cover': 'https://covers.openlibrary.org/b/id/8228691-L.jpg',
            'description': 'A story about teenage rebellion and alienation.',
            'isbn': '9780316769174',
            'rating': 4.3
        },
        {
            'id': 'book8',
            'title': 'Lord of the Flies',
            'author': 'William Golding',
            'cover': 'https://covers.openlibrary.org/b/id/8238427-L.jpg',
            'description': 'A novel about the descent into savagery.',
            'isbn': '9780399501487',
            'rating': 4.2
        }
    ]
    
    # Filter books based on query
    filtered = [b for b in all_books if query in b['title'].lower() or query in b['author'].lower()]
    
    if not filtered:
        filtered = all_books[:4]  # Return some books if no match
    
    return jsonify({'books': filtered, 'count': len(filtered)}), 200

# ==================== FAVORITES ROUTES ====================

@app.route('/addFavorite', methods=['POST'])
@require_auth
def add_favorite():
    data = request.json
    title = data.get('title', '').strip()
    author = data.get('author', '').strip()
    cover = data.get('cover', '')
    description = data.get('description', '')
    isbn = data.get('isbn', '')
    
    if not all([title, author]):
        return jsonify({'error': 'Title and author required'}), 400
    
    try:
        conn = get_db()
        c = conn.cursor()
        
        # Check if already in favorites
        c.execute('SELECT id FROM favorites WHERE user_id = ? AND book_title = ? AND book_author = ?',
                  (request.user_id, title, author))
        if c.fetchone():
            conn.close()
            return jsonify({'error': 'Book already in favorites'}), 409
        
        c.execute('''INSERT INTO favorites (user_id, book_title, book_author, book_cover, book_description, book_isbn)
                     VALUES (?, ?, ?, ?, ?, ?)''',
                  (request.user_id, title, author, cover, description, isbn))
        conn.commit()
        fav_id = c.lastrowid
        conn.close()
        
        return jsonify({
            'message': 'Added to favorites!',
            'favorite_id': fav_id
        }), 201
    except Exception as e:
        return jsonify({'error': f'Failed to add favorite: {str(e)}'}), 500

@app.route('/myFavorites', methods=['GET'])
@require_auth
def my_favorites():
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('''SELECT id, book_title as title, book_author as author, 
                            book_cover as cover, book_description as description,
                            book_isbn as isbn, added_at
                     FROM favorites WHERE user_id = ?
                     ORDER BY added_at DESC''',
                  (request.user_id,))
        favorites = c.fetchall()
        conn.close()
        
        favorites_list = [dict(fav) for fav in favorites]
        
        return jsonify({
            'favorites': favorites_list,
            'count': len(favorites_list)
        }), 200
    except Exception as e:
        return jsonify({'error': f'Failed to fetch favorites: {str(e)}'}), 500

@app.route('/removeFavorite/<int:fav_id>', methods=['DELETE'])
@require_auth
def remove_favorite(fav_id):
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('DELETE FROM favorites WHERE id = ? AND user_id = ?',
                  (fav_id, request.user_id))
        if c.rowcount == 0:
            conn.close()
            return jsonify({'error': 'Favorite not found'}), 404
        conn.commit()
        conn.close()
        
        return jsonify({'message': 'Removed from favorites'}), 200
    except Exception as e:
        return jsonify({'error': f'Failed to remove favorite: {str(e)}'}), 500

# ==================== BOOK MANAGEMENT ROUTES ====================

@app.route('/addBook', methods=['POST'])
@require_auth
def add_book():
    data = request.json
    title = data.get('title', '').strip()
    author = data.get('author', '').strip()
    cover_url = data.get('cover_url', '')
    description = data.get('description', '')
    isbn = data.get('isbn', '')
    rating = data.get('rating', 0)
    
    if not all([title, author]):
        return jsonify({'error': 'Title and author required'}), 400
    
    try:
        conn = get_db()
        c = conn.cursor()
        
        c.execute('SELECT id FROM books WHERE user_id = ? AND title = ? AND author = ?',
                  (request.user_id, title, author))
        if c.fetchone():
            conn.close()
            return jsonify({'error': 'Book already in your library'}), 409
        
        c.execute('''INSERT INTO books (user_id, title, author, cover_url, description, isbn, rating)
                     VALUES (?, ?, ?, ?, ?, ?, ?)''',
                  (request.user_id, title, author, cover_url, description, isbn, rating))
        conn.commit()
        book_id = c.lastrowid
        conn.close()
        
        return jsonify({
            'message': 'Book added to library',
            'book_id': book_id
        }), 201
    except Exception as e:
        return jsonify({'error': f'Failed to add book: {str(e)}'}), 500

@app.route('/myBooks', methods=['GET'])
@require_auth
def my_books():
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('''SELECT id, title, author, cover_url, description, isbn, rating, added_at
                     FROM books WHERE user_id = ?
                     ORDER BY added_at DESC''',
                  (request.user_id,))
        books = c.fetchall()
        conn.close()
        
        books_list = [dict(book) for book in books]
        
        return jsonify({
            'books': books_list,
            'count': len(books_list)
        }), 200
    except Exception as e:
        return jsonify({'error': f'Failed to fetch books: {str(e)}'}), 500

# ==================== EXCHANGE ROUTES ====================

@app.route('/exchange', methods=['GET'])
@require_auth
def get_exchange_books():
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('''SELECT b.id, b.title, b.author, b.cover_url, b.description, b.isbn, b.rating,
                            u.username as owner_username, u.id as owner_id, u.profile_photo as owner_photo
                     FROM books b
                     JOIN users u ON b.user_id = u.id
                     WHERE b.user_id != ?
                     ORDER BY b.added_at DESC''',
                  (request.user_id,))
        books = c.fetchall()
        conn.close()
        
        books_list = [dict(book) for book in books]
        
        return jsonify({
            'books': books_list,
            'count': len(books_list)
        }), 200
    except Exception as e:
        return jsonify({'error': f'Failed to fetch exchange books: {str(e)}'}), 500

@app.route('/requestExchange', methods=['POST'])
@require_auth
def request_exchange():
    data = request.json
    book_id = data.get('book_id')
    
    if not book_id:
        return jsonify({'error': 'Book ID required'}), 400
    
    try:
        conn = get_db()
        c = conn.cursor()
        
        c.execute('SELECT user_id FROM books WHERE id = ?', (book_id,))
        book = c.fetchone()
        
        if not book:
            conn.close()
            return jsonify({'error': 'Book not found'}), 404
        
        owner_id = book['user_id']
        
        if owner_id == request.user_id:
            conn.close()
            return jsonify({'error': 'Cannot request your own book'}), 400
        
        c.execute('''SELECT id FROM exchange_requests
                     WHERE requester_id = ? AND book_id = ? AND status = 'pending' ''',
                  (request.user_id, book_id))
        if c.fetchone():
            conn.close()
            return jsonify({'error': 'Request already pending'}), 409
        
        c.execute('''INSERT INTO exchange_requests (requester_id, owner_id, book_id, status)
                     VALUES (?, ?, ?, 'pending')''',
                  (request.user_id, owner_id, book_id))
        conn.commit()
        request_id = c.lastrowid
        conn.close()
        
        return jsonify({
            'message': 'Exchange request sent',
            'request_id': request_id
        }), 201
    except Exception as e:
        return jsonify({'error': f'Failed to create request: {str(e)}'}), 500

@app.route('/myRequests', methods=['GET'])
@require_auth
def my_requests():
    try:
        conn = get_db()
        c = conn.cursor()
        
        # Requests I sent
        c.execute('''SELECT er.id, er.status, er.created_at,
                            b.title, b.author, b.cover_url,
                            u.username as owner_username, u.profile_photo as owner_photo
                     FROM exchange_requests er
                     JOIN books b ON er.book_id = b.id
                     JOIN users u ON er.owner_id = u.id
                     WHERE er.requester_id = ?
                     ORDER BY er.created_at DESC''',
                  (request.user_id,))
        sent_requests = [dict(row) for row in c.fetchall()]
        
        # Requests I received
        c.execute('''SELECT er.id, er.status, er.created_at,
                            b.title, b.author, b.cover_url,
                            u.username as requester_username, u.profile_photo as requester_photo,
                            er.book_id
                     FROM exchange_requests er
                     JOIN books b ON er.book_id = b.id
                     JOIN users u ON er.requester_id = u.id
                     WHERE er.owner_id = ?
                     ORDER BY er.created_at DESC''',
                  (request.user_id,))
        received_requests = [dict(row) for row in c.fetchall()]
        
        conn.close()
        
        return jsonify({
            'sent': sent_requests,
            'received': received_requests,
            'sent_count': len(sent_requests),
            'received_count': len(received_requests)
        }), 200
    except Exception as e:
        return jsonify({'error': f'Failed to fetch requests: {str(e)}'}), 500

@app.route('/updateRequest/<int:request_id>', methods=['PUT'])
@require_auth
def update_request(request_id):
    data = request.json
    status = data.get('status')
    
    if status not in ['accepted', 'rejected']:
        return jsonify({'error': 'Invalid status'}), 400
    
    try:
        conn = get_db()
        c = conn.cursor()
        
        c.execute('SELECT owner_id, requester_id, book_id FROM exchange_requests WHERE id = ?', (request_id,))
        request_row = c.fetchone()
        
        if not request_row:
            conn.close()
            return jsonify({'error': 'Request not found'}), 404
        
        if request_row['owner_id'] != request.user_id:
            conn.close()
            return jsonify({'error': 'Unauthorized'}), 403
        
        c.execute('''UPDATE exchange_requests
                     SET status = ?, updated_at = CURRENT_TIMESTAMP
                     WHERE id = ?''',
                  (status, request_id))
        
        # If accepted, add to completed exchanges
        if status == 'accepted':
            c.execute('''INSERT INTO completed_exchanges (user1_id, user2_id, book_id)
                         VALUES (?, ?, ?)''',
                      (request_row['owner_id'], request_row['requester_id'], request_row['book_id']))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'message': f'Request {status}',
            'status': status
        }), 200
    except Exception as e:
        return jsonify({'error': f'Failed to update request: {str(e)}'}), 500

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        'status': 'healthy',
        'message': 'Book Exchange API is running',
        'active_sessions': len(active_tokens)
    }), 200

# ==================== RUN APPLICATION ====================

if __name__ == '__main__':
    print("🚀 Initializing Book Exchange Platform...")
    init_db()
    print("📚 Starting Flask server on http://localhost:5000")
    print("🔐 Using token-based authentication")
    print("⭐ Favorites system enabled!")
    app.run(debug=True, port=5000, host='0.0.0.0')