from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from sqlalchemy import Index, text
from sqlalchemy.sql import select, delete, insert, update

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///library.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'your-secret-key'

db = SQLAlchemy(app)

# Association tables for many-to-many relationships
book_authors = db.Table('book_authors',
    db.Column('book_id', db.Integer, db.ForeignKey('book.id'), primary_key=True),
    db.Column('author_id', db.Integer, db.ForeignKey('author.id'), primary_key=True)
)

book_genres = db.Table('book_genres',
    db.Column('book_id', db.Integer, db.ForeignKey('book.id'), primary_key=True),
    db.Column('genre_id', db.Integer, db.ForeignKey('genre.id'), primary_key=True)
)

# Models
class Book(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    isbn = db.Column(db.String(20), unique=True, nullable=False)
    publication_date = db.Column(db.Date, nullable=True)
    copies_available = db.Column(db.Integer, default=1)
    publisher_id = db.Column(db.Integer, db.ForeignKey('publisher.id'))
    publisher = db.relationship('Publisher', backref=db.backref('books', lazy=True))
    authors = db.relationship('Author', secondary=book_authors, lazy='subquery',
                              backref=db.backref('books', lazy=True))
    genres = db.relationship('Genre', secondary=book_genres, lazy='subquery',
                             backref=db.backref('books', lazy=True))

    def __repr__(self):
        return f'<Book {self.title}>'

class Author(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    biography = db.Column(db.Text, nullable=True)

    def __repr__(self):
        return f'<Author {self.name}>'

class Genre(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text, nullable=True)

    def __repr__(self):
        return f'<Genre {self.name}>'

class Publisher(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    address = db.Column(db.String(200), nullable=True)
    contact = db.Column(db.String(100), nullable=True)

    def __repr__(self):
        return f'<Publisher {self.name}>'

# Create database indexes
Index('ix_book_title', Book.title)
Index('ix_book_isbn', Book.isbn, unique=True)  # Although already unique by constraint
Index('ix_book_publication_date', Book.publication_date)
Index('ix_book_copies_available', Book.copies_available)
Index('ix_author_name', Author.name)
Index('ix_genre_name', Genre.name)
Index('ix_publisher_name', Publisher.name)

# Create stored procedures (SQLite doesn't support true stored procedures, so we use SQL functions)
# These will be created when the database is initialized
STORED_PROCEDURES = [
    """
    CREATE VIEW IF NOT EXISTS vw_book_details AS
    SELECT 
        b.id as book_id, 
        b.title, 
        b.isbn, 
        b.publication_date,
        b.copies_available,
        p.name as publisher_name,
        p.id as publisher_id
    FROM book b
    LEFT JOIN publisher p ON b.publisher_id = p.id
    """,
    
    """
    CREATE VIEW IF NOT EXISTS vw_book_authors AS
    SELECT 
        b.id as book_id,
        b.title as book_title,
        a.id as author_id,
        a.name as author_name
    FROM book b
    JOIN book_authors ba ON b.id = ba.book_id
    JOIN author a ON ba.author_id = a.id
    """,
    
    """
    CREATE VIEW IF NOT EXISTS vw_book_genres AS
    SELECT 
        b.id as book_id,
        b.title as book_title,
        g.id as genre_id,
        g.name as genre_name
    FROM book b
    JOIN book_genres bg ON b.id = bg.book_id
    JOIN genre g ON bg.genre_id = g.id
    """
]

# Routes
@app.route('/')
def index():
    # Using prepared statement with SQLAlchemy Core
    stmt = select(Book).order_by(Book.title)
    with db.engine.connect() as conn:
        result = conn.execute(stmt)
        books = result.all()
    return render_template('index.html', books=books)

@app.route('/book/search', methods=['GET', 'POST'])
def search_books():
    if request.method == 'POST':
        search_term = request.form['search_term']
        
        # Using prepared statement with parameter binding
        stmt = text("SELECT * FROM book WHERE title LIKE :search_term OR isbn LIKE :search_term")
        with db.engine.connect() as conn:
            result = conn.execute(stmt, {"search_term": f"%{search_term}%"})
            books = result.all()
        
        return render_template('search_results.html', books=books, search_term=search_term)
    
    return render_template('search_form.html')

@app.route('/book/new', methods=['GET', 'POST'])
def new_book():
    if request.method == 'POST':
        # Extract form data
        title = request.form['title']
        isbn = request.form['isbn']
        publisher_id = request.form['publisher']
        
        # Handle publication date
        pub_date_str = request.form['publication_date']
        if pub_date_str:
            pub_date = datetime.strptime(pub_date_str, '%Y-%m-%d')
        else:
            pub_date = None
            
        copies = int(request.form['copies_available'])
        
        try:
            # Using a prepared statement with SQLAlchemy Core
            stmt = insert(Book).values(
                title=title,
                isbn=isbn,
                publication_date=pub_date,
                copies_available=copies,
                publisher_id=publisher_id
            ).returning(Book.id)
            
            with db.engine.connect() as conn:
                with conn.begin():  # Start a transaction
                    result = conn.execute(stmt)
                    book_id = result.scalar_one()
                    
                    # Add authors using prepared statements
                    author_ids = request.form.getlist('authors')
                    for author_id in author_ids:
                        author_stmt = insert(book_authors).values(
                            book_id=book_id,
                            author_id=author_id
                        )
                        conn.execute(author_stmt)
                    
                    # Add genres using prepared statements
                    genre_ids = request.form.getlist('genres')
                    for genre_id in genre_ids:
                        genre_stmt = insert(book_genres).values(
                            book_id=book_id,
                            genre_id=genre_id
                        )
                        conn.execute(genre_stmt)
            
            flash('Book added successfully!', 'success')
            return redirect(url_for('index'))
        except Exception as e:
            flash(f'Error adding book: {str(e)}', 'danger')
    
    # GET request - show form
    publishers = Publisher.query.all()
    authors = Author.query.all()
    genres = Genre.query.all()
    return render_template('book_form.html', publishers=publishers, 
                          authors=authors, genres=genres, book=None)

@app.route('/book/edit/<int:id>', methods=['GET', 'POST'])
def edit_book(id):
    # Using ORM for retrieving the book
    book = Book.query.get_or_404(id)
    
    if request.method == 'POST':
        # Update book information using prepared statements
        try:
            title = request.form['title']
            isbn = request.form['isbn']
            publisher_id = request.form['publisher']
            
            pub_date_str = request.form['publication_date']
            if pub_date_str:
                pub_date = datetime.strptime(pub_date_str, '%Y-%m-%d')
            else:
                pub_date = None
                
            copies = int(request.form['copies_available'])
            
            # Using prepared statement for update
            with db.engine.connect() as conn:
                with conn.begin():  # Start a transaction
                    # Update book
                    update_stmt = update(Book).where(Book.id == id).values(
                        title=title,
                        isbn=isbn,
                        publication_date=pub_date,
                        copies_available=copies,
                        publisher_id=publisher_id
                    )
                    conn.execute(update_stmt)
                    
                    # Delete existing author associations
                    delete_authors_stmt = delete(book_authors).where(book_authors.c.book_id == id)
                    conn.execute(delete_authors_stmt)
                    
                    # Add new author associations
                    author_ids = request.form.getlist('authors')
                    for author_id in author_ids:
                        author_stmt = insert(book_authors).values(
                            book_id=id,
                            author_id=author_id
                        )
                        conn.execute(author_stmt)
                    
                    # Delete existing genre associations
                    delete_genres_stmt = delete(book_genres).where(book_genres.c.book_id == id)
                    conn.execute(delete_genres_stmt)
                    
                    # Add new genre associations
                    genre_ids = request.form.getlist('genres')
                    for genre_id in genre_ids:
                        genre_stmt = insert(book_genres).values(
                            book_id=id,
                            genre_id=genre_id
                        )
                        conn.execute(genre_stmt)
            
            flash('Book updated successfully!', 'success')
            return redirect(url_for('index'))
        except Exception as e:
            flash(f'Error updating book: {str(e)}', 'danger')
    
    # GET request - show form with book data
    publishers = Publisher.query.all()
    authors = Author.query.all()
    genres = Genre.query.all()
    return render_template('book_form.html', publishers=publishers, 
                          authors=authors, genres=genres, book=book)

@app.route('/book/delete/<int:id>', methods=['POST'])
def delete_book(id):
    try:
        # Using prepared statement for delete
        with db.engine.connect() as conn:
            with conn.begin():  # Start a transaction
                # Delete associations first
                delete_authors_stmt = delete(book_authors).where(book_authors.c.book_id == id)
                conn.execute(delete_authors_stmt)
                
                delete_genres_stmt = delete(book_genres).where(book_genres.c.book_id == id)
                conn.execute(delete_genres_stmt)
                
                # Delete the book
                delete_book_stmt = delete(Book).where(Book.id == id)
                conn.execute(delete_book_stmt)
        
        flash('Book deleted successfully!', 'success')
    except Exception as e:
        flash(f'Error deleting book: {str(e)}', 'danger')
        
    return redirect(url_for('index'))

@app.route('/book/details/<int:id>')
def book_details(id):
    # Use the stored procedure (view) to get book details
    stmt = text("""
        SELECT bd.*, 
               GROUP_CONCAT(DISTINCT ba.author_name) as authors,
               GROUP_CONCAT(DISTINCT bg.genre_name) as genres
        FROM vw_book_details bd
        LEFT JOIN vw_book_authors ba ON bd.book_id = ba.book_id
        LEFT JOIN vw_book_genres bg ON bd.book_id = bg.book_id
        WHERE bd.book_id = :book_id
        GROUP BY bd.book_id
    """)
    
    with db.engine.connect() as conn:
        result = conn.execute(stmt, {"book_id": id})
        book_details = result.fetchone()
        
    if not book_details:
        flash('Book not found', 'danger')
        return redirect(url_for('index'))
        
    return render_template('book_details.html', book=book_details)

# Routes for supporting tables (keeping the ORM approach for these)
@app.route('/authors')
def list_authors():
    authors = Author.query.all()
    return render_template('authors.html', authors=authors)

@app.route('/author/new', methods=['GET', 'POST'])
def new_author():
    if request.method == 'POST':
        name = request.form['name']
        biography = request.form['biography']
        
        # Using prepared statement
        stmt = insert(Author).values(name=name, biography=biography)
        
        try:
            with db.engine.connect() as conn:
                with conn.begin():
                    conn.execute(stmt)
            flash('Author added successfully!', 'success')
            return redirect(url_for('list_authors'))
        except Exception as e:
            flash(f'Error adding author: {str(e)}', 'danger')
    
    return render_template('author_form.html')


@app.route('/author/edit/<int:id>', methods=['GET', 'POST'])
def edit_author(id):
    author = Author.query.get_or_404(id)
    
    if request.method == 'POST':
        name = request.form['name']
        biography = request.form['biography']
        
        # Using prepared statement
        stmt = update(Author).where(Author.id == id).values(
            name=name, 
            biography=biography
        )
        
        try:
            with db.engine.connect() as conn:
                with conn.begin():
                    conn.execute(stmt)
            flash('Author updated successfully!', 'success')
            return redirect(url_for('list_authors'))
        except Exception as e:
            flash(f'Error updating author: {str(e)}', 'danger')
    
    return render_template('author_form.html', author=author)

@app.route('/author/delete/<int:id>', methods=['POST'])
def delete_author(id):  
    try:
        with db.engine.connect() as conn:
            # Start a single transaction for both operations
            with conn.begin():
                # Check if author has any books using prepared statement
                check_stmt = text("""
                    SELECT COUNT(*) as book_count 
                    FROM book_authors 
                    WHERE author_id = :author_id
                """)
                
                result = conn.execute(check_stmt, {"author_id": id})
                book_count = result.scalar()
                
                if book_count > 0:
                    # We need to roll back the transaction and return
                    # Since we're in a with block, the rollback happens automatically when we return
                    flash('Cannot delete author with associated books!', 'danger')
                    return redirect(url_for('list_authors'))
                
                # Delete the author using prepared statement
                delete_stmt = delete(Author).where(Author.id == id)
                conn.execute(delete_stmt)
                # The transaction will be committed automatically at the end of the with block
                
        flash('Author deleted successfully!', 'success')
    except Exception as e:
        flash(f'Error deleting author: {str(e)}', 'danger')
        
    return redirect(url_for('list_authors'))

@app.route('/publishers')
def list_publishers():
    publishers = Publisher.query.all()
    return render_template('publishers.html', publishers=publishers)

@app.route('/publisher/new', methods=['GET', 'POST'])
def new_publisher():
    if request.method == 'POST':
        name = request.form['name']
        address = request.form['address']
        contact = request.form['contact']
        
        # Using prepared statement
        stmt = insert(Publisher).values(
            name=name, 
            address=address, 
            contact=contact
        )
        
        try:
            with db.engine.connect() as conn:
                with conn.begin():
                    conn.execute(stmt)
            flash('Publisher added successfully!', 'success')
            return redirect(url_for('list_publishers'))
        except Exception as e:
            flash(f'Error adding publisher: {str(e)}', 'danger')
    
    return render_template('publisher_form.html', publisher=None)

@app.route('/publisher/edit/<int:id>', methods=['GET', 'POST'])
def edit_publisher(id):
    publisher = Publisher.query.get_or_404(id)
    
    if request.method == 'POST':
        name = request.form['name']
        address = request.form['address']
        contact = request.form['contact']
        
        # Using prepared statement
        stmt = update(Publisher).where(Publisher.id == id).values(
            name=name, 
            address=address, 
            contact=contact
        )
        
        try:
            with db.engine.connect() as conn:
                with conn.begin():
                    conn.execute(stmt)
            flash('Publisher updated successfully!', 'success')
            return redirect(url_for('list_publishers'))
        except Exception as e:
            flash(f'Error updating publisher: {str(e)}', 'danger')
    
    return render_template('publisher_form.html', publisher=publisher)

@app.route('/publisher/delete/<int:id>', methods=['POST'])
def delete_publisher(id):
    try:
        with db.engine.connect() as conn:
            # Start a single transaction for both operations
            with conn.begin():
                # Check if publisher has any books using prepared statement
                check_stmt = text("""
                    SELECT COUNT(*) as book_count 
                    FROM book 
                    WHERE publisher_id = :publisher_id
                """)
                
                result = conn.execute(check_stmt, {"publisher_id": id})
                book_count = result.scalar()
                
                if book_count > 0:
                    # We need to roll back the transaction and return
                    # Since we're in a with block, the rollback happens automatically when we return
                    flash('Cannot delete publisher with associated books!', 'danger')
                    return redirect(url_for('list_publishers'))
                
                # Delete the publisher using prepared statement
                delete_stmt = delete(Publisher).where(Publisher.id == id)
                conn.execute(delete_stmt)
                
                # The transaction will be committed automatically at the end of the with block
                
        flash('Publisher deleted successfully!', 'success')
    except Exception as e:
        flash(f'Error deleting publisher: {str(e)}', 'danger')
        
    return redirect(url_for('list_publishers'))

@app.route('/genres')
def list_genres():
    genres = Genre.query.all()
    return render_template('genres.html', genres=genres)

@app.route('/genre/new', methods=['GET', 'POST'])
def new_genre():
    if request.method == 'POST':
        name = request.form['name']
        description = request.form['description']
        
        # Using prepared statement
        stmt = insert(Genre).values(
            name=name, 
            description=description
        )
        
        try:
            with db.engine.connect() as conn:
                with conn.begin():
                    conn.execute(stmt)
            flash('Genre added successfully!', 'success')
            return redirect(url_for('list_genres'))
        except Exception as e:
            flash(f'Error adding genre: {str(e)}', 'danger')
    
    return render_template('genre_form.html', genre=None)

@app.route('/genre/edit/<int:id>', methods=['GET', 'POST'])
def edit_genre(id):
    genre = Genre.query.get_or_404(id)
    
    if request.method == 'POST':
        name = request.form['name']
        description = request.form['description']
        
        # Using prepared statement
        stmt = update(Genre).where(Genre.id == id).values(
            name=name, 
            description=description
        )
        
        try:
            with db.engine.connect() as conn:
                with conn.begin():
                    conn.execute(stmt)
            flash('Genre updated successfully!', 'success')
            return redirect(url_for('list_genres'))
        except Exception as e:
            flash(f'Error updating genre: {str(e)}', 'danger')
    
    return render_template('genre_form.html', genre=genre)

@app.route('/genre/delete/<int:id>', methods=['POST'])
def delete_genre(id):
    # Prepared statement to check if genre is associated with any books
    check_stmt = text("""
        SELECT COUNT(*) as book_count 
        FROM book_genres 
        WHERE genre_id = :genre_id
    """)
    
    try:
        # Start a transaction-aware connection
        with db.engine.begin() as conn:
            result = conn.execute(check_stmt, {"genre_id": id})
            book_count = result.scalar()
            
            if book_count > 0:
                flash('Cannot delete genre with associated books!', 'danger')
                return redirect(url_for('list_genres'))
            
            # Delete genre using raw SQL (prepared-style)
            delete_stmt = delete(Genre).where(Genre.id == id)
            conn.execute(delete_stmt)

        flash('Genre deleted successfully!', 'success')
    except Exception as e:
        flash(f'Error deleting genre: {str(e)}', 'danger')
        
    return redirect(url_for('list_genres'))

# Using stored procedures (views)
@app.route('/reports/books_by_genre')
def books_by_genre():
    stmt = text("""
        SELECT g.name as genre_name, COUNT(bg.book_id) as book_count
        FROM genre g
        LEFT JOIN book_genres bg ON g.id = bg.genre_id
        GROUP BY g.id, g.name
        ORDER BY book_count DESC
    """)
    
    with db.engine.connect() as conn:
        result = conn.execute(stmt)
        genre_stats = result.all()
        
    return render_template('report_books_by_genre.html', genre_stats=genre_stats)

@app.route('/reports/authors_by_books')
def authors_by_books():
    stmt = text("""
        SELECT a.name as author_name, COUNT(ba.book_id) as book_count
        FROM author a
        LEFT JOIN book_authors ba ON a.id = ba.author_id
        GROUP BY a.id, a.name
        ORDER BY book_count DESC
    """)
    
    with db.engine.connect() as conn:
        result = conn.execute(stmt)
        author_stats = result.all()
        
    return render_template('report_authors_by_books.html', author_stats=author_stats)

# Initialize the database
@app.cli.command('init-db')
def init_db_command():
    db.create_all()
    
    # Create stored procedures (views)
    with db.engine.connect() as conn:
        for proc in STORED_PROCEDURES:
            conn.execute(text(proc))
    
    # Add sample data
    if Author.query.count() == 0:
        authors = [
            Author(name='J.K. Rowling', biography='British author best known for the Harry Potter series'),
            Author(name='George Orwell', biography='English novelist and essayist'),
            Author(name='Jane Austen', biography='English novelist known for her six major novels')
        ]
        db.session.add_all(authors)
        
    if Genre.query.count() == 0:
        genres = [
            Genre(name='Fantasy', description='Fiction with supernatural elements'),
            Genre(name='Science Fiction', description='Fiction based on scientific discoveries or advanced technology'),
            Genre(name='Classic', description='Books of high quality that have stood the test of time')
        ]
        db.session.add_all(genres)
        
    if Publisher.query.count() == 0:
        publishers = [
            Publisher(name='Penguin Random House', address='1745 Broadway, New York, NY', contact='info@penguinrandomhouse.com'),
            Publisher(name='HarperCollins', address='195 Broadway, New York, NY', contact='info@harpercollins.com')
        ]
        db.session.add_all(publishers)
    
    db.session.commit()
    print('Database initialized with sample data and stored procedures!')

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5001, debug=True)