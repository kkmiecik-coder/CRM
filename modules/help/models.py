"""
Modele bazy danych dla modułu Help/Dokumentacja
"""
from datetime import datetime
from extensions import db


class HelpCategory(db.Model):
    """
    Model kategorii artykułów pomocy
    """
    __tablename__ = 'help_categories'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(100), nullable=False)
    icon = db.Column(db.String(50), default='📄')
    sort_order = db.Column(db.Integer, default=0)
    is_visible = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relacja do artykułów (one-to-many)
    articles = db.relationship('HelpArticle', backref='category', lazy='dynamic', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<HelpCategory {self.name}>'
    
    def to_dict(self):
        """Konwersja do słownika (dla JSON)"""
        return {
            'id': self.id,
            'name': self.name,
            'icon': self.icon,
            'sort_order': self.sort_order,
            'is_visible': self.is_visible,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'articles_count': self.articles.count()
        }


class HelpArticle(db.Model):
    """
    Model artykułu pomocy
    """
    __tablename__ = 'help_articles'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    category_id = db.Column(db.Integer, db.ForeignKey('help_categories.id', ondelete='RESTRICT'), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    slug = db.Column(db.String(255), unique=True, nullable=False, index=True)
    content = db.Column(db.Text, nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    views_count = db.Column(db.Integer, default=0)
    sort_order = db.Column(db.Integer, default=0)
    is_published = db.Column(db.Boolean, default=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relacja do autora
    author = db.relationship('User', backref='help_articles', lazy='joined')
    
    # Indeks FULLTEXT (dodamy w SQL)
    __table_args__ = (
        db.Index('idx_category', 'category_id'),
        db.Index('idx_published', 'is_published'),
    )
    
    def __repr__(self):
        return f'<HelpArticle {self.title}>'
    
    def to_dict(self, include_content=False):
        """Konwersja do słownika (dla JSON)"""
        data = {
            'id': self.id,
            'category_id': self.category_id,
            'category_name': self.category.name if self.category else None,
            'title': self.title,
            'slug': self.slug,
            'author_id': self.author_id,
            'author_name': self.author.name if self.author else None,
            'views_count': self.views_count,
            'sort_order': self.sort_order,
            'is_published': self.is_published,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
        
        if include_content:
            data['content'] = self.content
        
        return data
    
    def increment_views(self):
        """Zwiększ licznik wyświetleń"""
        self.views_count += 1
        db.session.commit()