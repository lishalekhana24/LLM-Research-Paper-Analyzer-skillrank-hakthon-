from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class Paper(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(300), nullable=False)
    authors = db.Column(db.String(500))
    abstract = db.Column(db.Text)
    full_text = db.Column(db.Text)
    summary = db.Column(db.Text)
    key_findings = db.Column(db.Text)
    gaps = db.Column(db.Text)
    future_work = db.Column(db.Text)
    pdf_path = db.Column(db.String(500))  