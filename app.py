import os
from flask import Flask, render_template, request, jsonify, redirect, url_for, send_from_directory
from flask_sqlalchemy import SQLAlchemy
import re
from openai import OpenAI
import fitz  # PyMuPDF for better text extraction
from models import db, Paper
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(os.path.dirname(__file__), 'papers.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
db.init_app(app)

client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

with app.app_context():
    db.create_all()


def extract_metadata(text):
    """Enhanced extraction for arXiv PDFs: Better regex for title/authors, preserve whitespace."""
    # Keep raw text for full view with preserved whitespace
    original_text = text
    
    # Split into lines, preserving all whitespace
    lines = [line for line in text.split('\n')]  # Keep original spacing
    
    # Title: First significant line (non-empty, capitalized)
    title = next((line.strip() for line in lines if line.strip() and (line[0].isupper() or len(line.strip()) > 10)), "Unknown Title")
    
    # Authors: After title, until "Abstract" or affiliations; handle arXiv format (names with superscripts)
    authors = "Unknown Authors"
    start_idx = lines.index(title.strip()) + 1 if title in lines else 0
    end_idx = len(lines)
    for i in range(start_idx, min(start_idx + 15, len(lines))):  # Check more lines
        line = lines[i].strip()
        if re.search(r'(?i)abstract|date|correspondence|affiliation', line):
            end_idx = i
            break
    author_block = ' '.join(lines[start_idx:end_idx]).strip()
    # Regex for authors: "First Last1, First Last2, ..." with optional superscripts
    author_match = re.search(r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*(?:\s*\d+(?:,\s*\d+)*)?(?:,\s*[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*(?:\s*\d+(?:,\s*\d+)*)?)*)', author_block)
    if author_match:
        authors = author_match.group(1).replace('\n', ' ').strip()
    
    # Abstract: After "Abstract", up to section 1/Introduction, preserve whitespace
    abstract_match = re.search(r'(?i)abstract\s*(.*?)(?=\n\s*\d+\s+|\n\s*1\s+introduction)', original_text, re.DOTALL | re.IGNORECASE)
    abstract = abstract_match.group(1).strip() if abstract_match else "Abstract not found"
    abstract = abstract.replace('\n', '<br>').replace('  ', '&nbsp;&nbsp;')  # Preserve line breaks and spaces
    
    # Full text: Raw text with preserved formatting
    full_text = original_text.replace('\n', '<br>').replace('  ', '&nbsp;&nbsp;')
    
    return title, authors, abstract, full_text

def generate_summary(text):
    prompt = """
    Summarize this AI/CS research paper concisely (150-200 words).
    Structure as:
    - Main Contributions: [bullet points]
    - Methodology: [brief description]
    - Key Results: [bullet points]
    Focus on innovations and implications.
    Paper text: {text}
    """.format(text=text.replace('<br>', '\n').replace('&nbsp;&nbsp;', ' ')[:3000])
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3
    )
    return response.choices[0].message.content.replace('\n', '<br>')

def extract_key_findings(summary):
    prompt = """
    Extract 3-5 key findings and contributions as bullet points from this summary.
    Summary: {summary}
    """.format(summary=summary)
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content.replace('\n', '<br>')

def analyze_gaps(summary):
    prompt = """
    Analyze this AI/CS paper summary for research gaps.
    Structure as:
    - Limitations: [bullet points]
    - Future Work: [3-5 specific suggestions]
    - Unexplored Areas: [opportunities]
    Be realistic.
    Summary: {summary}
    """.format(summary=summary)
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5
    )
    return response.choices[0].message.content.replace('\n', '<br>')

@app.route('/', methods=['GET', 'POST'])
def upload():
    if request.method == 'POST':
        if 'file' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        if file and file.filename.lower().endswith('.pdf'):
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
            file.save(filepath)
            
            try:
                with fitz.open(filepath) as pdf:
                    text = '\n'.join(page.get_text() for page in pdf)  # Raw text with whitespace
                print(f"Extracted text length: {len(text)}")
                
                title, authors, abstract, full_text = extract_metadata(text)
                
                paper = Paper(title=title, authors=authors, abstract=abstract, full_text=full_text, pdf_path=filepath)
                db.session.add(paper)
                db.session.commit()
                
                print(f"Saved paper ID: {paper.id}, Title: {title}, Authors: {authors}, PDF: {filepath}")
                return redirect(url_for('view_paper', paper_id=paper.id))
            except Exception as e:
                return jsonify({'error': f'Extraction failed: {str(e)}'}), 500
        return jsonify({'error': 'Invalid file type'}), 400
    return render_template('upload.html')

@app.route('/paper/<int:paper_id>')
def view_paper(paper_id):
    paper = Paper.query.get_or_404(paper_id)
    # Extract filename from pdf_path for the template
    pdf_filename = os.path.basename(paper.pdf_path)
    return render_template('view.html', paper=paper, pdf_filename=pdf_filename)

@app.route('/uploads/<path:filename>')
def serve_pdf(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/summarize/<int:paper_id>')
def summarize_paper(paper_id):
    paper = Paper.query.get_or_404(paper_id)
    if not paper.summary:
        summary = generate_summary(paper.full_text.replace('<br>', '\n').replace('&nbsp;&nbsp;', '  '))
        findings = extract_key_findings(summary)
        paper.summary = summary
        paper.key_findings = findings
        db.session.commit()
    return jsonify({'summary': paper.summary, 'key_findings': paper.key_findings})

@app.route('/gaps/<int:paper_id>')
def gaps_paper(paper_id):
    paper = Paper.query.get_or_404(paper_id)
    if not paper.gaps:
        gaps_text = analyze_gaps(paper.summary.replace('<br>', '\n') or paper.abstract.replace('<br>', '\n'))
        if 'Future Work:' in gaps_text:
            paper.gaps, paper.future_work = gaps_text.split('Future Work:', 1)
            paper.future_work = paper.future_work.strip()
        else:
            paper.gaps = gaps_text
            paper.future_work = "Future directions: Explore multimodal extensions."
        db.session.commit()
    return jsonify({'gaps': paper.gaps, 'future_work': paper.future_work})

@app.route('/search')
def search():
    query = request.args.get('q', '').lower()
    area = request.args.get('area', '').lower()
    papers = Paper.query.filter(
        db.or_(
            Paper.title.ilike(f'%{query}%'),
            Paper.summary.ilike(f'%{query}%'),
            Paper.full_text.ilike(f'%{query}%')
        )
    )
    if area:
        papers = papers.filter(Paper.summary.ilike(f'%{area}%'))
    papers = papers.all()
    results = [{'title': p.title, 'authors': p.authors} for p in papers]  # Only title/authors
    return render_template('search.html', results=results, query=query, area=area)

@app.route('/compare/<int:id1>/<int:id2>')
def compare_papers(id1, id2):
    p1 = Paper.query.get_or_404(id1)
    p2 = Paper.query.get_or_404(id2)
    
    # Generate summary for p1 if it doesn't exist
    if not p1.summary:
        summary = generate_summary(p1.full_text.replace('<br>', '\n').replace('&nbsp;&nbsp;', '  '))
        findings = extract_key_findings(summary)
        p1.summary = summary
        p1.key_findings = findings
        db.session.commit()
    
    # Generate summary for p2 if it doesn't exist
    if not p2.summary:
        summary = generate_summary(p2.full_text.replace('<br>', '\n').replace('&nbsp;&nbsp;', '  '))
        findings = extract_key_findings(summary)
        p2.summary = summary
        p2.key_findings = findings
        db.session.commit()
    
    prompt = f"""
    Compare these two AI/CS papers for gaps and synergies.
    Paper 1 ({p1.title}): Summary - {p1.summary.replace('<br>', '\n')[:500]}
    Paper 2 ({p2.title}): Summary - {p2.summary.replace('<br>', '\n')[:500]}
    Output:
    - Similarities: [bullets]
    - Differences/Gaps: [bullets with opportunities]
    - Suggested Joint Future Work: [3 ideas]
    """
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )
    return jsonify({'comparison': response.choices[0].message.content.replace('\n', '<br>')})

if __name__ == '__main__':
    app.run(debug=True)