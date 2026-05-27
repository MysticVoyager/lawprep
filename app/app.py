"""
MH-CET Law 2027 - Learning Portal
A local tutoring platform for exam preparation.
"""

import os
import sys
import re
import json
import sqlite3
import random
from datetime import datetime, timedelta
from contextlib import contextmanager

from flask import (
    Flask, render_template, request, jsonify,
    redirect, url_for, session, g, Response
)

# Load .env if present (so GEMINI_API_KEY, ELEVENLABS_API_KEY etc. are picked up)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))
except ImportError:
    pass

# pdf_parser is only needed if the database has to be (re)built from PDFs.
# Most users run with the pre-built lawprep.db, so make this import optional.
try:
    from pdf_parser import parse_all_pdfs
except Exception:  # pragma: no cover - pdfplumber missing or PDFs absent
    parse_all_pdfs = None

app = Flask(__name__)
# Secret key for Flask sessions. Set FLASK_SECRET_KEY in your environment
# (or .env file) for production. The default below is only safe for local
# single-user use on your own machine.
app.secret_key = os.environ.get(
    'FLASK_SECRET_KEY',
    'change-me-set-FLASK_SECRET_KEY-in-env'
)

from markupsafe import Markup, escape as html_escape

@app.template_filter('nl2br')
def nl2br_filter(text):
    """Escape HTML then convert newlines to <br> tags."""
    return Markup(html_escape(text).replace('\n', Markup('<br>')))

DB_PATH = os.path.join(os.path.dirname(__file__), 'lawprep.db')
PDF_DIR = os.path.join(os.path.dirname(__file__), '..')


# ---------------------------------------------------------------------------
# DATABASE
# ---------------------------------------------------------------------------

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db


@app.teardown_appcontext
def close_db(exception):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript('''
        CREATE TABLE IF NOT EXISTS subjects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            description TEXT,
            icon TEXT DEFAULT '📚',
            color TEXT DEFAULT '#6366f1'
        );

        CREATE TABLE IF NOT EXISTS topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            description TEXT,
            FOREIGN KEY (subject_id) REFERENCES subjects(id),
            UNIQUE(subject_id, name)
        );

        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id INTEGER NOT NULL,
            passage TEXT,
            question_text TEXT NOT NULL,
            option_a TEXT NOT NULL,
            option_b TEXT NOT NULL,
            option_c TEXT,
            option_d TEXT,
            correct_answer TEXT,
            explanation TEXT,
            source TEXT,
            difficulty INTEGER DEFAULT 2,
            FOREIGN KEY (topic_id) REFERENCES topics(id)
        );

        CREATE TABLE IF NOT EXISTS mock_tests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            total_questions INTEGER,
            time_limit_minutes INTEGER DEFAULT 150,
            source TEXT
        );

        CREATE TABLE IF NOT EXISTS mock_test_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mock_test_id INTEGER NOT NULL,
            question_id INTEGER NOT NULL,
            question_order INTEGER,
            section TEXT,
            FOREIGN KEY (mock_test_id) REFERENCES mock_tests(id),
            FOREIGN KEY (question_id) REFERENCES questions(id)
        );

        CREATE TABLE IF NOT EXISTS quiz_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            quiz_type TEXT NOT NULL,
            topic_id INTEGER,
            mock_test_id INTEGER,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP,
            total_questions INTEGER DEFAULT 0,
            correct_answers INTEGER DEFAULT 0,
            score_percentage REAL DEFAULT 0,
            time_taken_seconds INTEGER DEFAULT 0,
            FOREIGN KEY (topic_id) REFERENCES topics(id),
            FOREIGN KEY (mock_test_id) REFERENCES mock_tests(id)
        );

        CREATE TABLE IF NOT EXISTS question_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            quiz_attempt_id INTEGER,
            question_id INTEGER NOT NULL,
            selected_answer TEXT,
            is_correct BOOLEAN,
            attempted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (quiz_attempt_id) REFERENCES quiz_attempts(id),
            FOREIGN KEY (question_id) REFERENCES questions(id)
        );

        CREATE TABLE IF NOT EXISTS bookmarks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id INTEGER NOT NULL,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (question_id) REFERENCES questions(id),
            UNIQUE(question_id)
        );

        CREATE TABLE IF NOT EXISTS study_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id INTEGER,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            duration_minutes INTEGER DEFAULT 0,
            cards_reviewed INTEGER DEFAULT 0,
            FOREIGN KEY (topic_id) REFERENCES topics(id)
        );

        CREATE TABLE IF NOT EXISTS lessons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            key_concepts TEXT,
            order_num INTEGER DEFAULT 0,
            lesson_type TEXT DEFAULT 'passage',
            FOREIGN KEY (topic_id) REFERENCES topics(id)
        );

        CREATE TABLE IF NOT EXISTS lesson_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lesson_id INTEGER NOT NULL,
            status TEXT DEFAULT 'not_started',
            completed_at TIMESTAMP,
            notes TEXT,
            confidence INTEGER DEFAULT 0,
            FOREIGN KEY (lesson_id) REFERENCES lessons(id),
            UNIQUE(lesson_id)
        );

        CREATE TABLE IF NOT EXISTS syllabus_topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_id INTEGER NOT NULL,
            topic_name TEXT NOT NULL,
            key_concepts TEXT,
            FOREIGN KEY (subject_id) REFERENCES subjects(id)
        );

        CREATE TABLE IF NOT EXISTS mock_test_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            quiz_attempt_id INTEGER,
            test_type TEXT NOT NULL,
            english_score INTEGER DEFAULT 0,
            english_total INTEGER DEFAULT 0,
            gk_score INTEGER DEFAULT 0,
            gk_total INTEGER DEFAULT 0,
            legal_score INTEGER DEFAULT 0,
            legal_total INTEGER DEFAULT 0,
            logical_score INTEGER DEFAULT 0,
            logical_total INTEGER DEFAULT 0,
            total_score INTEGER DEFAULT 0,
            total_possible INTEGER DEFAULT 0,
            percentile_estimate REAL DEFAULT 0,
            time_taken_seconds INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (quiz_attempt_id) REFERENCES quiz_attempts(id)
        );

        CREATE TABLE IF NOT EXISTS question_time_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_attempt_id INTEGER,
            question_id INTEGER NOT NULL,
            time_seconds INTEGER DEFAULT 0,
            FOREIGN KEY (question_attempt_id) REFERENCES question_attempts(id),
            FOREIGN KEY (question_id) REFERENCES questions(id)
        );

        CREATE TABLE IF NOT EXISTS tts_usage (
            id INTEGER PRIMARY KEY,
            chars_used INTEGER DEFAULT 0,
            month TEXT UNIQUE NOT NULL
        );
    ''')
    db.commit()
    db.close()


# ---------------------------------------------------------------------------
# DATA LOADING
# ---------------------------------------------------------------------------

def load_data_from_pdfs():
    """Parse PDFs and load into database."""
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")

    # Check if already loaded
    count = db.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    if count > 0:
        print(f"Database already has {count} questions. Skipping import.")
        db.close()
        return

    if parse_all_pdfs is None:
        print(
            "pdf_parser is unavailable (install pdfplumber and place source "
            "PDFs in the parent folder if you want to rebuild the database)."
        )
        db.close()
        return

    print("Loading data from PDFs...")
    results = parse_all_pdfs(PDF_DIR)

    # Define subjects
    subjects_data = {
        'Legal Reasoning': ('Legal aptitude, contract law, torts, criminal law and more', '⚖️', '#2dd4bf'),
        'Mathematics': ('Algebra, arithmetic, geometry, data interpretation', '🔢', '#fbbf24'),
        'General Knowledge': ('Current affairs, Indian polity, history, geography', '🌍', '#34d399'),
        'Logical Reasoning': ('Analytical reasoning, critical thinking, puzzles', '🧠', '#38bdf8'),
        'English': ('Reading comprehension, grammar, vocabulary', '📝', '#f9a8d4'),
    }

    subject_ids = {}
    for name, (desc, icon, color) in subjects_data.items():
        db.execute(
            "INSERT OR IGNORE INTO subjects (name, description, icon, color) VALUES (?, ?, ?, ?)",
            (name, desc, icon, color)
        )
        row = db.execute("SELECT id FROM subjects WHERE name = ?", (name,)).fetchone()
        subject_ids[name] = row['id']

    db.commit()

    topic_ids = {}

    def get_or_create_topic(subject_name, topic_name):
        key = (subject_name, topic_name)
        if key not in topic_ids:
            sid = subject_ids.get(subject_name, subject_ids.get('Legal Reasoning'))
            db.execute(
                "INSERT OR IGNORE INTO topics (subject_id, name) VALUES (?, ?)",
                (sid, topic_name)
            )
            row = db.execute(
                "SELECT id FROM topics WHERE subject_id = ? AND name = ?",
                (sid, topic_name)
            ).fetchone()
            topic_ids[key] = row['id']
        return topic_ids[key]

    # Load maths questions
    for q in results['maths']:
        tid = get_or_create_topic('Mathematics', f"Set {q.get('set_num', 1)}")
        db.execute('''
            INSERT INTO questions (topic_id, passage, question_text, option_a, option_b, option_c, option_d, correct_answer, explanation, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (tid, q.get('passage', ''), q['question_text'], q['option_a'], q['option_b'],
              q.get('option_c', ''), q.get('option_d', ''), q.get('correct_answer', ''),
              q.get('explanation', ''), q.get('source', '')))

    # Load legal reasoning questions
    for q in results['legal_reasoning']:
        tid = get_or_create_topic('Legal Reasoning', q.get('topic', 'General'))
        db.execute('''
            INSERT INTO questions (topic_id, passage, question_text, option_a, option_b, option_c, option_d, correct_answer, explanation, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (tid, q.get('passage', ''), q['question_text'], q['option_a'], q['option_b'],
              q.get('option_c', ''), q.get('option_d', ''), q.get('correct_answer', ''),
              q.get('explanation', ''), q.get('source', '')))

    # Load sample paper questions
    for q in results['sample_paper']:
        tid = get_or_create_topic(q.get('subject', 'Legal Reasoning'), q.get('topic', 'General'))
        db.execute('''
            INSERT INTO questions (topic_id, passage, question_text, option_a, option_b, option_c, option_d, correct_answer, explanation, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (tid, q.get('passage', ''), q['question_text'], q['option_a'], q['option_b'],
              q.get('option_c', ''), q.get('option_d', ''), q.get('correct_answer', ''),
              q.get('explanation', ''), q.get('source', '')))

    db.commit()

    # Load mock tests
    for mt in results['mock_tests']:
        test_num = mt['test_num']
        db.execute(
            "INSERT INTO mock_tests (name, total_questions, time_limit_minutes, source) VALUES (?, ?, ?, ?)",
            (f"Mock Test {test_num}", mt['total_questions'], 150, f"Mock Test {test_num}")
        )
        mt_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        for q in mt['questions']:
            tid = get_or_create_topic(q.get('subject', 'Legal Reasoning'), q.get('topic', 'General'))
            db.execute('''
                INSERT INTO questions (topic_id, passage, question_text, option_a, option_b, option_c, option_d, correct_answer, explanation, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (tid, q.get('passage', ''), q['question_text'], q['option_a'], q['option_b'],
                  q.get('option_c', ''), q.get('option_d', ''), q.get('correct_answer', ''),
                  q.get('explanation', ''), q.get('source', '')))
            q_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

            db.execute('''
                INSERT INTO mock_test_questions (mock_test_id, question_id, question_order, section)
                VALUES (?, ?, ?, ?)
            ''', (mt_id, q_id, q.get('question_num', 0), q.get('subject', '')))

    db.commit()

    # Load previous year questions
    for q in results.get('previous_year', []):
        tid = get_or_create_topic(q.get('subject', 'General Knowledge'), q.get('topic', 'GK & Current Affairs'))
        db.execute('''
            INSERT INTO questions (topic_id, passage, question_text, option_a, option_b, option_c, option_d, correct_answer, explanation, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (tid, q.get('passage', ''), q['question_text'], q.get('option_a', ''), q.get('option_b', ''),
              q.get('option_c', ''), q.get('option_d', ''), q.get('correct_answer', ''),
              q.get('explanation', ''), q.get('source', '')))

    db.commit()

    # Load teaching lessons
    order_counter = {}
    for lesson in results.get('lessons', []):
        tid = get_or_create_topic(lesson['subject'], lesson['topic'])
        topic_key = tid
        order_counter[topic_key] = order_counter.get(topic_key, 0) + 1
        db.execute('''
            INSERT INTO lessons (topic_id, title, content, order_num, lesson_type)
            VALUES (?, ?, ?, ?, 'passage')
        ''', (tid, lesson['title'], lesson['content'], order_counter[topic_key]))

    db.commit()

    # Load syllabus content as lessons
    syllabus = results.get('syllabus', {})
    for subj_name, subj_data in syllabus.items():
        for topic_info in subj_data.get('topics', []):
            tid = get_or_create_topic(subj_name, topic_info['name'])
            concepts = topic_info.get('key_concepts', [])
            if concepts:
                concepts_text = '\n'.join(f'• {c}' for c in concepts)
                db.execute('''
                    INSERT INTO lessons (topic_id, title, content, order_num, lesson_type)
                    VALUES (?, ?, ?, 0, 'syllabus')
                ''', (tid, f"Key Concepts: {topic_info['name']}", concepts_text))

                # Also store in syllabus_topics
                sid = subject_ids.get(subj_name)
                if sid:
                    db.execute('''
                        INSERT OR IGNORE INTO syllabus_topics (subject_id, topic_name, key_concepts)
                        VALUES (?, ?, ?)
                    ''', (sid, topic_info['name'], concepts_text))

    db.commit()

    total = db.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    topics_count = db.execute("SELECT COUNT(*) FROM topics").fetchone()[0]
    lessons_count = db.execute("SELECT COUNT(*) FROM lessons").fetchone()[0]
    print(f"Loaded {total} questions, {lessons_count} lessons across {topics_count} topics")
    db.close()


# ---------------------------------------------------------------------------
# ROUTES
# ---------------------------------------------------------------------------

@app.route('/')
def dashboard():
    db = get_db()

    # Stats
    total_questions = db.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    total_attempts = db.execute("SELECT COUNT(*) FROM question_attempts").fetchone()[0]
    correct_attempts = db.execute("SELECT COUNT(*) FROM question_attempts WHERE is_correct = 1").fetchone()[0]
    total_quizzes = db.execute("SELECT COUNT(*) FROM quiz_attempts WHERE completed_at IS NOT NULL").fetchone()[0]

    accuracy = round(correct_attempts / total_attempts * 100, 1) if total_attempts > 0 else 0

    # Subject-wise stats
    subjects = db.execute('''
        SELECT s.*, COUNT(DISTINCT q.id) as question_count,
               COUNT(DISTINCT qa.id) as attempted,
               SUM(CASE WHEN qa.is_correct = 1 THEN 1 ELSE 0 END) as correct
        FROM subjects s
        LEFT JOIN topics t ON t.subject_id = s.id
        LEFT JOIN questions q ON q.topic_id = t.id
        LEFT JOIN question_attempts qa ON qa.question_id = q.id
        GROUP BY s.id
        ORDER BY s.name
    ''').fetchall()

    # Recent activity
    recent = db.execute('''
        SELECT qa.*, t.name as topic_name, s.name as subject_name, s.icon
        FROM quiz_attempts qa
        LEFT JOIN topics t ON qa.topic_id = t.id
        LEFT JOIN subjects s ON t.subject_id = s.id
        WHERE qa.completed_at IS NOT NULL
        ORDER BY qa.completed_at DESC
        LIMIT 10
    ''').fetchall()

    # Study streak (days with activity)
    streak = db.execute('''
        SELECT COUNT(DISTINCT DATE(attempted_at)) as days
        FROM question_attempts
        WHERE attempted_at >= DATE('now', '-30 days')
    ''').fetchone()['days']

    # Mock test count
    mock_count = db.execute("SELECT COUNT(*) FROM mock_tests").fetchone()[0]

    return render_template('dashboard.html',
        total_questions=total_questions,
        total_attempts=total_attempts,
        total_quizzes=total_quizzes,
        accuracy=accuracy,
        subjects=subjects,
        recent=recent,
        streak=streak,
        mock_count=mock_count
    )


@app.route('/subjects')
def subjects():
    db = get_db()
    subjects = db.execute('''
        SELECT s.*, COUNT(DISTINCT q.id) as question_count,
               COUNT(DISTINCT t.id) as topic_count,
               COUNT(DISTINCT qa.id) as attempted,
               SUM(CASE WHEN qa.is_correct = 1 THEN 1 ELSE 0 END) as correct
        FROM subjects s
        LEFT JOIN topics t ON t.subject_id = s.id
        LEFT JOIN questions q ON q.topic_id = t.id
        LEFT JOIN question_attempts qa ON qa.question_id = q.id
        GROUP BY s.id
        ORDER BY s.name
    ''').fetchall()

    return render_template('subjects.html', subjects=subjects)


@app.route('/subject/<int:subject_id>')
def subject_detail(subject_id):
    db = get_db()
    subject = db.execute("SELECT * FROM subjects WHERE id = ?", (subject_id,)).fetchone()

    topics = db.execute('''
        SELECT t.*, COUNT(DISTINCT q.id) as question_count,
               COUNT(DISTINCT qa.id) as attempted,
               SUM(CASE WHEN qa.is_correct = 1 THEN 1 ELSE 0 END) as correct
        FROM topics t
        LEFT JOIN questions q ON q.topic_id = t.id
        LEFT JOIN question_attempts qa ON qa.question_id = q.id
        WHERE t.subject_id = ?
        GROUP BY t.id
        ORDER BY t.name
    ''', (subject_id,)).fetchall()

    return render_template('subject_detail.html', subject=subject, topics=topics)


# ---------------------------------------------------------------------------
# LEARN & TUTOR ROUTES
# ---------------------------------------------------------------------------

@app.route('/learn')
def learn():
    db = get_db()
    subjects = db.execute('''
        SELECT s.*, COUNT(DISTINCT l.id) as lesson_count,
               COUNT(DISTINCT CASE WHEN lp.status = 'completed' THEN l.id END) as completed_lessons,
               COUNT(DISTINCT t.id) as topic_count
        FROM subjects s
        LEFT JOIN topics t ON t.subject_id = s.id
        LEFT JOIN lessons l ON l.topic_id = t.id
        LEFT JOIN lesson_progress lp ON lp.lesson_id = l.id
        GROUP BY s.id
        ORDER BY s.name
    ''').fetchall()

    total_lessons = db.execute("SELECT COUNT(*) FROM lessons").fetchone()[0]
    completed_lessons = db.execute("SELECT COUNT(*) FROM lesson_progress WHERE status = 'completed'").fetchone()[0]

    return render_template('learn.html',
        subjects=subjects,
        total_lessons=total_lessons,
        completed_lessons=completed_lessons
    )


@app.route('/learn/<int:subject_id>')
def learn_subject(subject_id):
    db = get_db()
    subject = db.execute("SELECT * FROM subjects WHERE id = ?", (subject_id,)).fetchone()

    topics = db.execute('''
        SELECT t.*,
               COUNT(DISTINCT l.id) as lesson_count,
               COUNT(DISTINCT CASE WHEN lp.status = 'completed' THEN l.id END) as completed_lessons,
               COUNT(DISTINCT q.id) as question_count
        FROM topics t
        LEFT JOIN lessons l ON l.topic_id = t.id
        LEFT JOIN lesson_progress lp ON lp.lesson_id = l.id
        LEFT JOIN questions q ON q.topic_id = t.id
        WHERE t.subject_id = ?
        GROUP BY t.id
        ORDER BY t.name
    ''', (subject_id,)).fetchall()

    return render_template('learn_subject.html', subject=subject, topics=topics)


@app.route('/learn/topic/<int:topic_id>')
def learn_topic(topic_id):
    db = get_db()
    topic = db.execute('''
        SELECT t.*, s.name as subject_name, s.icon, s.color, s.id as subject_id
        FROM topics t JOIN subjects s ON t.subject_id = s.id
        WHERE t.id = ?
    ''', (topic_id,)).fetchone()

    lessons = db.execute('''
        SELECT l.*, lp.status as progress_status, lp.confidence
        FROM lessons l
        LEFT JOIN lesson_progress lp ON lp.lesson_id = l.id
        WHERE l.topic_id = ?
        ORDER BY l.order_num, l.id
    ''', (topic_id,)).fetchall()

    question_count = db.execute(
        "SELECT COUNT(*) FROM questions WHERE topic_id = ?", (topic_id,)
    ).fetchone()[0]

    return render_template('learn_topic.html',
        topic=topic, lessons=lessons, question_count=question_count)


@app.route('/lesson/<int:lesson_id>')
def view_lesson(lesson_id):
    db = get_db()
    lesson = db.execute('''
        SELECT l.*, t.name as topic_name, s.name as subject_name, s.icon, s.color,
               t.id as topic_id, s.id as subject_id,
               lp.status as progress_status, lp.confidence, lp.notes as user_notes
        FROM lessons l
        JOIN topics t ON l.topic_id = t.id
        JOIN subjects s ON t.subject_id = s.id
        LEFT JOIN lesson_progress lp ON lp.lesson_id = l.id
        WHERE l.id = ?
    ''', (lesson_id,)).fetchone()

    # Get prev/next lessons in same topic
    all_lessons = db.execute('''
        SELECT id, title FROM lessons WHERE topic_id = ?
        ORDER BY order_num, id
    ''', (lesson['topic_id'],)).fetchall()

    prev_lesson = next_lesson = None
    for i, l in enumerate(all_lessons):
        if l['id'] == lesson_id:
            if i > 0:
                prev_lesson = all_lessons[i - 1]
            if i < len(all_lessons) - 1:
                next_lesson = all_lessons[i + 1]
            break

    # Find related questions (questions in same topic with matching passage content)
    related_questions = db.execute('''
        SELECT q.* FROM questions q
        WHERE q.topic_id = ? AND q.option_a != ''
        ORDER BY RANDOM() LIMIT 3
    ''', (lesson['topic_id'],)).fetchall()

    content_paragraphs = _classify_paragraphs(lesson['content'])

    # Load cached extras (takeaways + quiz); if missing, will be generated client-side
    extras = None
    if lesson['key_concepts']:
        try:
            kc = json.loads(lesson['key_concepts'])
            if 'takeaways' in kc and 'quiz' in kc:
                extras = kc
        except Exception:
            pass

    return render_template('lesson.html',
        lesson=lesson,
        prev_lesson=prev_lesson,
        next_lesson=next_lesson,
        related_questions=related_questions,
        total_in_topic=len(all_lessons),
        content_paragraphs=content_paragraphs,
        extras=extras,
    )


@app.route('/api/lesson_progress', methods=['POST'])
def update_lesson_progress():
    data = request.json
    db = get_db()
    lesson_id = data['lesson_id']
    status = data.get('status', 'completed')
    confidence = data.get('confidence', 3)
    notes = data.get('notes', '')

    db.execute('''
        INSERT INTO lesson_progress (lesson_id, status, completed_at, confidence, notes)
        VALUES (?, ?, CURRENT_TIMESTAMP, ?, ?)
        ON CONFLICT(lesson_id) DO UPDATE SET
            status = excluded.status,
            completed_at = excluded.completed_at,
            confidence = excluded.confidence,
            notes = CASE WHEN excluded.notes != '' THEN excluded.notes ELSE lesson_progress.notes END
    ''', (lesson_id, status, confidence, notes))
    db.commit()

    return jsonify({'status': 'ok'})


@app.route('/api/explain', methods=['POST'])
def api_explain():
    """Stream a tutor explanation for a lesson paragraph via Claude Haiku."""
    try:
        import anthropic
    except ImportError:
        return jsonify({
            'error': 'The "anthropic" package is not installed. '
                     'Run `pip install anthropic` to enable the Claude tutor.'
        }), 503

    if not os.environ.get('ANTHROPIC_API_KEY', '').strip():
        return jsonify({
            'error': 'ANTHROPIC_API_KEY is not set. Add it to your .env file '
                     'to enable the Claude tutor explanation feature.'
        }), 503

    data = request.get_json(silent=True) or {}
    text = (data.get('text') or '').strip()
    deeper = data.get('deeper', False)
    prev_exp = (data.get('prev_explanation') or '').strip()

    if not text and not prev_exp:
        return jsonify({'error': 'no text provided'}), 400

    SYSTEM_PROMPT = (
        "You are an enthusiastic law tutor teaching a 17-year-old student "
        "who is preparing for MH-CET Law exam in India. The student just "
        "heard this concept being read aloud and wants a deeper explanation.\n"
        "Your job:\n"
        "- Explain like a teacher talking to a student face to face\n"
        "- Use simple everyday Indian examples (autos, chai, cricket, "
        "Bollywood, college life — things a young Indian student relates to)\n"
        "- Break it down step by step\n"
        "- Point out exactly what the examiner will test from this\n"
        "- End with one memory trick to never forget this concept\n"
        "- Speak in a warm, encouraging tone\n"
        "- Keep it under 200 words so TTS reads it in under 90 seconds"
    )

    if deeper and prev_exp:
        user_msg = (
            f"I explained this concept earlier:\n\n{prev_exp}\n\n"
            f"The student wants to go even deeper. Give a richer explanation "
            f"with more detail, another example, and sharper exam tips."
        )
    else:
        user_msg = f"Explain this concept to me:\n\n{text}"

    def generate():
        client = anthropic.Anthropic()
        with client.messages.stream(
            model="claude-haiku-4-5",
            max_tokens=400,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}]
        ) as stream:
            for chunk in stream.text_stream:
                yield f"data: {json.dumps({'text': chunk})}\n\n"
        yield "data: [DONE]\n\n"

    return app.response_class(
        generate(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
        }
    )


# ---------------------------------------------------------------------------
# Lesson paragraph classification
# ---------------------------------------------------------------------------

def _classify_text_block(text):
    """Return the display type of a paragraph block."""
    first = text.split('\n')[0].strip()
    # Numbered list item (1. / 2) / 3.)
    if re.match(r'^\d+[\.\)]\s+\S', first):
        return 'list_paragraph' if len(text) >= 150 else 'list_item'
    # Single-letter acronym line: C - Confidentiality
    if re.match(r'^[A-Z]\s*[-–—]\s+\S', first) and len(text) < 150:
        return 'acronym'
    if len(text) < 80:
        return 'short'
    return 'paragraph'


def _classify_paragraphs(raw_content):
    """Return list of {text, type, show_explain} dicts for lesson rendering."""
    raw = (raw_content or '').strip()
    raw = re.sub(r'\n{3,}', '\n\n', raw)
    raw = '\n'.join(line.rstrip() for line in raw.splitlines())

    result = []
    for chunk in (p.strip() for p in raw.split('\n\n') if p.strip()):
        lines = chunk.split('\n')
        first = lines[0].strip()

        # Section heading (SECTION N — TITLE)
        if re.match(r'^SECTION\s+\d+\s*[—\-–]', first, re.I):
            result.append({'text': first, 'type': 'heading', 'show_explain': False})
            rest = '\n'.join(lines[1:]).strip()
            if rest:
                btype = _classify_text_block(rest)
                result.append({
                    'text': rest, 'type': btype,
                    'show_explain': btype in ('paragraph', 'list_paragraph') and len(rest) >= 100,
                })
        elif len(chunk) < 40:
            result.append({'text': chunk, 'type': 'short', 'show_explain': False})
        else:
            btype = _classify_text_block(chunk)
            result.append({
                'text': chunk, 'type': btype,
                'show_explain': btype in ('paragraph', 'list_paragraph') and len(chunk) >= 100,
            })

    return result


# ---------------------------------------------------------------------------
# Lesson extras — key takeaways + practice quiz (Gemini-generated, DB-cached)
# ---------------------------------------------------------------------------

_EXTRAS_PROMPT = """You are creating study aids for an MH-CET Law 2027 exam portal.

Subject: {subject}
Topic: {topic}

Lesson content:
{content}

{scenario_hint}

Generate a single valid JSON object (no markdown, no code fences):
{{
  "takeaways": [
    "Specific, exam-relevant point from this exact lesson",
    "Specific, exam-relevant point from this exact lesson",
    "Specific, exam-relevant point from this exact lesson",
    "Specific, exam-relevant point from this exact lesson"
  ],
  "quiz": {{
    "scenario": "{scenario_placeholder}",
    "question": "Based on the above, which of the following is correct?",
    "options": [
      {{"letter": "A", "text": "first option text"}},
      {{"letter": "B", "text": "second option text"}},
      {{"letter": "C", "text": "third option text"}},
      {{"letter": "D", "text": "fourth option text"}}
    ],
    "correct": "one of A/B/C/D",
    "explanation": "2-3 sentences explaining why the correct answer is right and why the others are wrong."
  }}
}}

Rules:
- Takeaways must be SPECIFIC to this lesson content, not generic advice
- Quiz options: exactly one is correct, three are plausible-but-wrong distractors
- The correct answer letter must match one of A/B/C/D
- Return ONLY the JSON object, nothing else"""


def _extract_section7_scenario(content: str) -> str:
    """Return the Section 7 scenario paragraph if present, else empty string."""
    m = re.search(r'SECTION\s+7\s*[—\-–][^\n]*\n+(.+)', content, re.I | re.DOTALL)
    if m:
        scenario = m.group(1).strip()
        # Take first paragraph only
        scenario = scenario.split('\n\n')[0].strip()
        if len(scenario) > 50:
            return scenario
    return ''


def _generate_extras(lesson_id, content, topic, subject):
    """Call Gemini to produce takeaways + quiz. Cache result in DB. Return dict or None."""
    api_key = os.environ.get('GEMINI_API_KEY', '').strip()
    if not api_key:
        return None
    try:
        from google import genai as ggenai
        client = ggenai.Client(api_key=api_key)

        existing_scenario = _extract_section7_scenario(content)
        if existing_scenario:
            scenario_hint = f'IMPORTANT: Use this exact scenario for the quiz (it is the Section 7 practice scenario from the lesson):\n"""\n{existing_scenario}\n"""'
            scenario_placeholder = existing_scenario.replace('"', '\\"')[:200] + '...'
        else:
            scenario_hint = 'Create an original 2-3 sentence factual scenario that tests a key concept from this lesson.'
            scenario_placeholder = 'A 2-3 sentence factual scenario based on this lesson'

        prompt = _EXTRAS_PROMPT.format(
            subject=subject, topic=topic, content=content[:4000],
            scenario_hint=scenario_hint, scenario_placeholder=scenario_placeholder,
        )
        resp = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
        raw = (resp.text or '').strip()
        # Strip any accidental markdown fences
        raw = re.sub(r'^```(?:json)?\n?', '', raw)
        raw = re.sub(r'\n?```$', '', raw.strip())
        extras = json.loads(raw)
        assert 'takeaways' in extras and 'quiz' in extras
        quiz = extras['quiz']
        assert len(quiz['options']) == 4
        assert quiz.get('correct') in ('A', 'B', 'C', 'D')
        # Cache in DB
        db = get_db()
        db.execute('UPDATE lessons SET key_concepts=? WHERE id=?',
                   (json.dumps(extras), lesson_id))
        db.commit()
        return extras
    except Exception as e:
        app.logger.warning(f'_generate_extras lesson {lesson_id}: {e}')
        return None


@app.route('/api/lesson-extras/<int:lesson_id>', methods=['POST'])
def api_lesson_extras(lesson_id):
    """Generate (or return cached) takeaways + quiz for a lesson."""
    db = get_db()
    lesson = db.execute(
        '''SELECT l.*, t.name as topic_name, s.name as subject_name
           FROM lessons l
           JOIN topics t ON l.topic_id = t.id
           JOIN subjects s ON t.subject_id = s.id
           WHERE l.id = ?''', (lesson_id,)
    ).fetchone()
    if not lesson:
        return jsonify({'error': 'not found'}), 404

    # Return cached if valid
    if lesson['key_concepts']:
        try:
            kc = json.loads(lesson['key_concepts'])
            if 'takeaways' in kc and 'quiz' in kc:
                return jsonify({'ok': True, 'extras': kc})
        except Exception:
            pass

    extras = _generate_extras(
        lesson_id, lesson['content'], lesson['topic_name'], lesson['subject_name']
    )
    if extras:
        return jsonify({'ok': True, 'extras': extras})
    return jsonify({'ok': False, 'error': 'generation failed'}), 500


# ---------------------------------------------------------------------------
# ElevenLabs TTS utilities
# ---------------------------------------------------------------------------

def _clean_text_for_tts(text):
    """Strip markdown, symbols and excess whitespace before sending to TTS."""
    text = re.sub(r'\*{1,3}([^*]*)\*{1,3}', r'\1', text)   # bold/italic
    text = re.sub(r'_{1,3}([^_]*)_{1,3}', r'\1', text)     # underscores
    text = re.sub(r'~~([^~]*)~~', r'\1', text)              # strikethrough
    text = re.sub(r'#{1,6}\s+', '', text)                   # headings
    text = re.sub(r'`[^`]*`', '', text)                     # inline code
    text = re.sub(r'\[([^\]]*)\]\([^)]+\)', r'\1', text)   # markdown links
    text = re.sub(r'\[([^\]]*)\]', r'\1', text)             # bare brackets
    text = re.sub(r'\(([^)]*)\)', r'\1', text)              # parens
    text = re.sub(r'[•→►]', '', text)                       # bullets
    text = re.sub(r'(?m):\s*$', '.', text)                  # trailing colon → period
    text = text.replace('_', ' ')
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def _chunk_text(text, max_chars=2500):
    """Split at sentence boundaries, never exceeding max_chars."""
    if len(text) <= max_chars:
        return [text]
    sentences = re.split(r'(?<=[.!?])\s+', text)
    chunks, current = [], ''
    for s in sentences:
        if len(current) + len(s) + 1 <= max_chars:
            current = (current + ' ' + s).strip()
        else:
            if current:
                chunks.append(current)
            current = s[:max_chars]
    if current:
        chunks.append(current)
    return chunks or [text[:max_chars]]


@app.route('/api/tts', methods=['POST'])
def api_tts():
    """Call ElevenLabs TTS and return audio/mpeg. Tracks character usage."""
    import requests as req

    api_key = os.environ.get('ELEVENLABS_API_KEY', '').strip()
    if not api_key:
        return jsonify({'error': 'ElevenLabs API key not configured'}), 500

    data = request.get_json(silent=True) or {}
    raw_text = (data.get('text') or '').strip()
    voice_id = data.get('voice_id', '21m00Tcm4TlvDq8ikWAM')
    if not raw_text:
        return jsonify({'error': 'no text'}), 400

    text = _clean_text_for_tts(raw_text)
    char_count = len(text)
    month = datetime.now().strftime('%Y-%m')

    db = get_db()
    row = db.execute('SELECT id, chars_used FROM tts_usage WHERE month=?', (month,)).fetchone()
    existing_used = row['chars_used'] if row else 0

    if existing_used >= 10000:
        return jsonify({'error': 'quota_exceeded', 'chars_used': existing_used}), 429

    chunks = _chunk_text(text)
    audio_parts = []

    for chunk in chunks:
        el_resp = req.post(
            f'https://api.elevenlabs.io/v1/text-to-speech/{voice_id}',
            headers={
                'xi-api-key': api_key,
                'Content-Type': 'application/json',
                'Accept': 'audio/mpeg',
            },
            json={
                'text': chunk,
                'model_id': 'eleven_monolingual_v1',
                'voice_settings': {
                    'stability': 0.5,
                    'similarity_boost': 0.75,
                },
            },
            timeout=30,
        )
        if el_resp.status_code != 200:
            return jsonify({'error': f'ElevenLabs {el_resp.status_code}', 'detail': el_resp.text[:200]}), 502
        audio_parts.append(el_resp.content)

    # Track usage after successful generation
    if row:
        db.execute('UPDATE tts_usage SET chars_used=chars_used+? WHERE month=?', (char_count, month))
    else:
        db.execute('INSERT INTO tts_usage (chars_used, month) VALUES (?,?)', (char_count, month))
    db.commit()

    audio_bytes = b''.join(audio_parts)
    return Response(audio_bytes, mimetype='audio/mpeg',
                    headers={'Cache-Control': 'no-cache'})


@app.route('/api/tts-usage')
def api_tts_usage():
    """Return current month ElevenLabs character usage."""
    month = datetime.now().strftime('%Y-%m')
    db = get_db()
    row = db.execute('SELECT chars_used FROM tts_usage WHERE month=?', (month,)).fetchone()
    used = row['chars_used'] if row else 0
    free_tier = 10000
    return jsonify({
        'chars_used': used,
        'chars_remaining': max(0, free_tier - used),
        'free_tier': free_tier,
        'month': month,
    })


def _rule_based_explanation(text, deeper=False, depth=0):
    """
    Fallback explanation when Gemini API is unavailable.
    Generates structured, exam-focused explanations from the paragraph text.
    """
    words = text.lower()

    # Detect subject domain from keywords
    domain_examples = {
        ('offer', 'acceptance', 'contract', 'consideration', 'agreement', 'promise'):
            ("Think of it like this: when you book an Ola cab, you make an OFFER by "
             "requesting a ride. The driver ACCEPTS. That is a contract! The fare is "
             "the consideration — what each side gives.",
             "Contract = OFFER + ACCEPTANCE + CONSIDERATION. No consideration = no contract!",
             "Remember: O-A-C — Offer, Acceptance, Consideration. Like 'OAC' sounds like 'Oak' tree — a strong contract stands firm like an oak."),
        ('ipc', 'section', 'punishment', 'offence', 'crime', 'culpable', 'murder', 'theft'):
            ("Imagine someone steals a cricket bat from your college. The IPC tells us "
             "exactly which section applies, what the punishment is, and whether bail is possible. "
             "The law is very specific — each crime has its own rules.",
             "The examiner will ask you the exact section number, whether the offence is cognizable or bailable, and the punishment.",
             "For IPC sections: learn the NUMBER, the ACT, and the PUNISHMENT. Think N-A-P: like taking a nap before remembering the law!"),
        ('constitution', 'fundamental', 'article', 'right', 'directive', 'amendment'):
            ("The Constitution is like the rulebook of India — even the Prime Minister must "
             "follow it! Fundamental Rights are YOUR rights that no one can take away. "
             "Like Article 19 gives you freedom of speech — you can criticise even a Bollywood film!",
             "MH-CET loves Article numbers! Learn Articles 12-35 (Fundamental Rights) and which rights can be suspended during Emergency.",
             "DRPSC — six Fundamental Rights: Dignity, Religion, Property (removed), Speech, Constitution remedies, Equality. Make a sentence: 'Don't Restrict People's Special Constitutional Equality'."),
        ('tort', 'negligence', 'liability', 'damages', 'plaintiff', 'defendant', 'injury'):
            ("Tort is a civil wrong — not a crime, but still wrong! Imagine your neighbour's "
             "dog bites you. You cannot send him to jail (that is criminal law) but you can "
             "SUE him for compensation. That is tort law!",
             "Know the difference: Tort = civil wrong = compensation. Crime = criminal wrong = punishment. The examiner WILL test this distinction.",
             "PIPL — Plaintiff (you), Injury, Proximity, Liability. Like 'people injured please litigate'!"),
        ('jurisdiction', 'court', 'appeal', 'high court', 'supreme court', 'magistrate'):
            ("Jurisdiction is like the boundary of a court's power. A Magistrate Court in "
             "Mumbai cannot decide a case from Delhi! Think of courts like cricket stadiums — "
             "each stadium hosts only its own matches.",
             "Original vs Appellate jurisdiction is a favourite exam topic. Original = first hearing. Appellate = reviewing lower court decision.",
             "J-O-A-T: Jurisdiction, Original, Appellate, Transfer. 'Just One Appeal at a Time!'"),
    }

    selected_example = selected_tip = selected_trick = None
    for keywords, (example, tip, trick) in domain_examples.items():
        if any(kw in words for kw in keywords):
            selected_example = example
            selected_tip = tip
            selected_trick = trick
            break

    # Generic fallback if no domain detected
    if not selected_example:
        selected_example = (
            "Think of law as the rules of a game — like cricket. Every player (person) "
            "has rights AND responsibilities. When someone breaks a rule, there is a "
            "consequence. Law works the same way in real life!"
        )
        selected_tip = (
            "For MH-CET, always focus on: (1) the exact legal term, (2) its definition, "
            "and (3) any exceptions. The examiner tests precision, not just general knowledge."
        )
        selected_trick = (
            "Make a short story using the key terms. The weirder the story, the better you remember it!"
        )

    # Build the explanation
    sentences = [s.strip() for s in re.split(r'[.!?]', text) if len(s.strip()) > 10]
    core = sentences[0] if sentences else text[:120]

    if deeper and depth > 0:
        result = (
            f"Great — let's go even deeper! {core}.\n\n"
            f"Here is a different angle: {selected_example}\n\n"
            f"Advanced exam tip: {selected_tip} Also remember that exceptions and "
            f"special cases are where most students lose marks — always read the full question!\n\n"
            f"Deeper memory trick: {selected_trick}"
        )
    else:
        result = (
            f"Let me break this down simply! {core}.\n\n"
            f"{selected_example}\n\n"
            f"Exam tip: {selected_tip}\n\n"
            f"Memory trick: {selected_trick}"
        )

    return result


@app.route('/api/tutor-explain', methods=['POST'])
def api_tutor_explain():
    """Get a tutor explanation — Gemini Flash primary, rule-based fallback."""
    data = request.get_json(silent=True) or {}
    text = (data.get('text') or '').strip()
    deeper = data.get('deeper', False)
    prev_exp = (data.get('prev_explanation') or '').strip()
    depth = int(data.get('depth', 0))

    if not text and not prev_exp:
        return jsonify({'error': 'no text'}), 400

    TUTOR_RULES = (
        "You are an enthusiastic law tutor teaching a 17-year-old student "
        "preparing for the MH-CET Law exam in India. Speak like a teacher "
        "face to face with a young student.\n\n"
        "Rules:\n"
        "- Use simple everyday Indian examples (chai, cricket, auto-rickshaw, "
        "college, Bollywood — things a young Indian student relates to)\n"
        "- Explain step by step in plain English\n"
        "- Tell them exactly what the examiner will test from this\n"
        "- End with one powerful memory trick\n"
        "- Warm and encouraging tone\n"
        "- Maximum 150 words — it will be read aloud by text-to-speech\n\n"
    )

    if deeper and prev_exp:
        prompt = (
            TUTOR_RULES
            + f"Previous explanation (level {depth}):\n{prev_exp}\n\n"
            + "Now go even deeper — fresh examples, more detail, sharper exam tips. "
            + "Don't repeat what was already said."
        )
    else:
        prompt = TUTOR_RULES + f"Concept to explain:\n{text}"

    # Try Gemini first
    api_key = os.environ.get('GEMINI_API_KEY', '').strip()
    if api_key:
        try:
            from google import genai as ggenai
            client = ggenai.Client(api_key=api_key)
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
            )
            explanation = response.text.strip()
            return jsonify({'explanation': explanation, 'ok': True, 'source': 'gemini'})
        except Exception as e:
            # Log and fall through to rule-based
            app.logger.warning(f'Gemini tutor-explain failed: {e}')

    # Rule-based fallback — always works, zero API calls
    explanation = _rule_based_explanation(text or prev_exp, deeper=deeper, depth=depth)
    return jsonify({'explanation': explanation, 'ok': True, 'source': 'local'})


@app.route('/tutor/<int:topic_id>')
def tutor(topic_id):
    """Interactive tutor mode: teach concept → quiz → feedback loop."""
    db = get_db()
    topic = db.execute('''
        SELECT t.*, s.name as subject_name, s.icon, s.color
        FROM topics t JOIN subjects s ON t.subject_id = s.id
        WHERE t.id = ?
    ''', (topic_id,)).fetchone()

    # Get lessons that haven't been completed or have low confidence
    lessons = db.execute('''
        SELECT l.*, lp.status as progress_status, lp.confidence
        FROM lessons l
        LEFT JOIN lesson_progress lp ON lp.lesson_id = l.id
        WHERE l.topic_id = ? AND l.content != ''
        ORDER BY
            CASE WHEN lp.status IS NULL OR lp.status != 'completed' THEN 0 ELSE 1 END,
            CASE WHEN lp.confidence IS NULL THEN 0 ELSE lp.confidence END,
            l.order_num, l.id
        LIMIT 5
    ''', (topic_id,)).fetchall()

    # Get questions for this topic for the quiz portion
    questions = db.execute('''
        SELECT * FROM questions
        WHERE topic_id = ? AND option_a != '' AND option_b != ''
        ORDER BY RANDOM()
        LIMIT 10
    ''', (topic_id,)).fetchall()

    # If no questions in this specific topic, pull from sibling topics in same subject
    if not questions:
        questions = db.execute('''
            SELECT q.* FROM questions q
            JOIN topics t ON q.topic_id = t.id
            WHERE t.subject_id = (SELECT subject_id FROM topics WHERE id = ?)
            AND q.option_a != '' AND q.option_b != ''
            ORDER BY RANDOM()
            LIMIT 10
        ''', (topic_id,)).fetchall()

    # Create quiz attempt for tracking
    db.execute('''
        INSERT INTO quiz_attempts (quiz_type, topic_id, total_questions)
        VALUES ('tutor', ?, ?)
    ''', (topic_id, len(questions)))
    attempt_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.commit()

    return render_template('tutor.html',
        topic=topic, lessons=lessons, questions=questions, attempt_id=attempt_id)


@app.route('/study/<int:topic_id>')
def study(topic_id):
    db = get_db()
    topic = db.execute('''
        SELECT t.*, s.name as subject_name, s.icon, s.color
        FROM topics t JOIN subjects s ON t.subject_id = s.id
        WHERE t.id = ?
    ''', (topic_id,)).fetchone()

    questions = db.execute('''
        SELECT q.*,
               (SELECT COUNT(*) FROM question_attempts qa WHERE qa.question_id = q.id) as attempt_count,
               (SELECT is_correct FROM question_attempts qa WHERE qa.question_id = q.id ORDER BY qa.attempted_at DESC LIMIT 1) as last_result,
               (SELECT COUNT(*) FROM bookmarks b WHERE b.question_id = q.id) as is_bookmarked
        FROM questions q
        WHERE q.topic_id = ?
        ORDER BY q.id
    ''', (topic_id,)).fetchall()

    return render_template('study.html', topic=topic, questions=questions)


@app.route('/quiz/<int:topic_id>')
def quiz(topic_id):
    db = get_db()
    topic = db.execute('''
        SELECT t.*, s.name as subject_name, s.icon, s.color
        FROM topics t JOIN subjects s ON t.subject_id = s.id
        WHERE t.id = ?
    ''', (topic_id,)).fetchone()

    # Get questions for this topic, randomized
    limit = int(request.args.get('count', 10))
    questions = db.execute('''
        SELECT * FROM questions
        WHERE topic_id = ?
        AND option_a != '' AND option_b != ''
        ORDER BY RANDOM()
        LIMIT ?
    ''', (topic_id, limit)).fetchall()

    # If no questions in this topic, try sibling topics in same subject
    if not questions:
        questions = db.execute('''
            SELECT q.* FROM questions q
            JOIN topics t ON q.topic_id = t.id
            WHERE t.subject_id = (SELECT subject_id FROM topics WHERE id = ?)
            AND q.option_a != '' AND q.option_b != ''
            ORDER BY RANDOM()
            LIMIT ?
        ''', (topic_id, limit)).fetchall()

    if not questions:
        return redirect(url_for('subject_detail', subject_id=topic['subject_id'] if topic else 1))

    # Create quiz attempt
    db.execute('''
        INSERT INTO quiz_attempts (quiz_type, topic_id, total_questions)
        VALUES ('practice', ?, ?)
    ''', (topic_id, len(questions)))
    attempt_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.commit()

    return render_template('quiz.html',
        topic=topic, questions=questions, attempt_id=attempt_id)


@app.route('/quiz/quick')
def quick_quiz():
    """Quick mixed quiz across all subjects."""
    db = get_db()
    count = int(request.args.get('count', 20))

    questions = db.execute('''
        SELECT q.*, t.name as topic_name, s.name as subject_name
        FROM questions q
        JOIN topics t ON q.topic_id = t.id
        JOIN subjects s ON t.subject_id = s.id
        WHERE q.option_a != '' AND q.option_b != '' AND q.correct_answer != ''
        ORDER BY RANDOM()
        LIMIT ?
    ''', (count,)).fetchall()

    db.execute('''
        INSERT INTO quiz_attempts (quiz_type, total_questions)
        VALUES ('quick', ?)
    ''', (len(questions),))
    attempt_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.commit()

    topic = {'name': 'Quick Quiz', 'subject_name': 'Mixed', 'icon': '⚡', 'color': '#f59e0b'}
    return render_template('quiz.html',
        topic=topic, questions=questions, attempt_id=attempt_id)


@app.route('/api/submit_answer', methods=['POST'])
def submit_answer():
    data = request.json
    db = get_db()

    question_id = data['question_id']
    selected = data['selected_answer']
    attempt_id = data.get('attempt_id')
    time_seconds = data.get('time_seconds', 0)

    # Get correct answer
    q = db.execute("SELECT * FROM questions WHERE id = ?", (question_id,)).fetchone()
    is_correct = selected.upper() == (q['correct_answer'] or '').upper() if q['correct_answer'] else None

    db.execute('''
        INSERT INTO question_attempts (quiz_attempt_id, question_id, selected_answer, is_correct)
        VALUES (?, ?, ?, ?)
    ''', (attempt_id, question_id, selected, is_correct))
    qa_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

    # Record time per question if provided
    if time_seconds and time_seconds > 0:
        try:
            db.execute('''
                INSERT INTO question_time_log (question_attempt_id, question_id, time_seconds)
                VALUES (?, ?, ?)
            ''', (qa_id, question_id, time_seconds))
        except Exception:
            pass  # table may not exist yet

    db.commit()

    return jsonify({
        'correct': is_correct,
        'correct_answer': q['correct_answer'],
        'explanation': q['explanation'] or 'No explanation available for this question.',
        'passage': q['passage'] or ''
    })


@app.route('/api/complete_quiz', methods=['POST'])
def complete_quiz():
    data = request.json
    db = get_db()

    attempt_id = data['attempt_id']
    time_taken = data.get('time_taken', 0)

    # Calculate results
    stats = db.execute('''
        SELECT COUNT(*) as total,
               SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END) as correct
        FROM question_attempts
        WHERE quiz_attempt_id = ?
    ''', (attempt_id,)).fetchone()

    total = stats['total'] or 0
    correct = stats['correct'] or 0
    score = round(correct / total * 100, 1) if total > 0 else 0

    db.execute('''
        UPDATE quiz_attempts
        SET completed_at = CURRENT_TIMESTAMP,
            total_questions = ?,
            correct_answers = ?,
            score_percentage = ?,
            time_taken_seconds = ?
        WHERE id = ?
    ''', (total, correct, score, time_taken, attempt_id))

    # Calculate section-wise breakdown
    section_data = db.execute('''
        SELECT s.name as subject_name,
               COUNT(qat.id) as total,
               SUM(CASE WHEN qat.is_correct = 1 THEN 1 ELSE 0 END) as correct
        FROM question_attempts qat
        JOIN questions q ON qat.question_id = q.id
        JOIN topics t ON q.topic_id = t.id
        JOIN subjects s ON t.subject_id = s.id
        WHERE qat.quiz_attempt_id = ?
        GROUP BY s.id
    ''', (attempt_id,)).fetchall()

    section_breakdown = {}
    eng_s, eng_t = 0, 0
    gk_s, gk_t = 0, 0
    legal_s, legal_t = 0, 0
    logical_s, logical_t = 0, 0

    for row in section_data:
        subj = row['subject_name']
        section_breakdown[subj] = {
            'correct': row['correct'] or 0,
            'total': row['total'] or 0,
            'accuracy': round((row['correct'] or 0) / row['total'] * 100, 1) if row['total'] else 0
        }
        if subj == 'English':
            eng_s, eng_t = row['correct'] or 0, row['total'] or 0
        elif subj == 'General Knowledge':
            gk_s, gk_t = row['correct'] or 0, row['total'] or 0
        elif subj == 'Legal Reasoning':
            legal_s, legal_t = row['correct'] or 0, row['total'] or 0
        elif subj == 'Logical Reasoning':
            logical_s, logical_t = row['correct'] or 0, row['total'] or 0

    # Determine test type
    attempt_row = db.execute("SELECT quiz_type FROM quiz_attempts WHERE id = ?", (attempt_id,)).fetchone()
    test_type = attempt_row['quiz_type'] if attempt_row else 'practice'

    # Percentile estimation calibrated for MH-CET Law 2027
    # Basis: 120 questions, no negative marking, GLC cutoff ~110+/120 (99th pct)
    if score >= 92:    # 110+/120
        percentile = 99.5
    elif score >= 88:  # 105+/120
        percentile = 99
    elif score >= 83:  # 100+/120 (KC Law cutoff)
        percentile = 97
    elif score >= 79:  # 95+/120
        percentile = 95
    elif score >= 75:  # 90+/120
        percentile = 90
    elif score >= 67:  # 80+/120
        percentile = 80
    elif score >= 58:  # 70+/120
        percentile = 65
    elif score >= 50:
        percentile = 50
    elif score >= 40:
        percentile = 32
    else:
        percentile = max(5, score * 0.5)

    # Store section-wise results in mock_test_results
    try:
        db.execute('''
            INSERT INTO mock_test_results
                (quiz_attempt_id, test_type, english_score, english_total,
                 gk_score, gk_total, legal_score, legal_total,
                 logical_score, logical_total, total_score, total_possible,
                 percentile_estimate, time_taken_seconds)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (attempt_id, test_type, eng_s, eng_t, gk_s, gk_t,
              legal_s, legal_t, logical_s, logical_t,
              correct, total, percentile, time_taken))
    except Exception:
        pass  # table may not exist

    db.commit()

    return jsonify({
        'total': total,
        'correct': correct,
        'score': score,
        'attempt_id': attempt_id,
        'sections': section_breakdown,
        'percentile': percentile
    })


@app.route('/results/<int:attempt_id>')
def results(attempt_id):
    db = get_db()

    attempt = db.execute('''
        SELECT qa.*, t.name as topic_name, s.name as subject_name, s.icon
        FROM quiz_attempts qa
        LEFT JOIN topics t ON qa.topic_id = t.id
        LEFT JOIN subjects s ON t.subject_id = s.id
        WHERE qa.id = ?
    ''', (attempt_id,)).fetchone()

    questions = db.execute('''
        SELECT qat.*, q.question_text, q.passage, q.option_a, q.option_b, q.option_c, q.option_d,
               q.correct_answer, q.explanation, t.name as topic_name, s.name as subject_name
        FROM question_attempts qat
        JOIN questions q ON qat.question_id = q.id
        JOIN topics t ON q.topic_id = t.id
        JOIN subjects s ON t.subject_id = s.id
        WHERE qat.quiz_attempt_id = ?
        ORDER BY qat.id
    ''', (attempt_id,)).fetchall()

    # Subject-wise breakdown
    breakdown = {}
    for q in questions:
        subj = q['subject_name']
        if subj not in breakdown:
            breakdown[subj] = {'total': 0, 'correct': 0}
        breakdown[subj]['total'] += 1
        if q['is_correct']:
            breakdown[subj]['correct'] += 1

    # Fetch mock_test_results for percentile and section data
    mock_result = None
    try:
        mock_result = db.execute('''
            SELECT * FROM mock_test_results WHERE quiz_attempt_id = ?
        ''', (attempt_id,)).fetchone()
    except Exception:
        pass

    # Identify weak topics from this attempt
    weak_topics = db.execute('''
        SELECT t.name as topic_name, s.name as subject_name,
               COUNT(qat.id) as total,
               SUM(CASE WHEN qat.is_correct = 1 THEN 1 ELSE 0 END) as correct
        FROM question_attempts qat
        JOIN questions q ON qat.question_id = q.id
        JOIN topics t ON q.topic_id = t.id
        JOIN subjects s ON t.subject_id = s.id
        WHERE qat.quiz_attempt_id = ?
        GROUP BY t.id
        HAVING COUNT(qat.id) >= 2
        ORDER BY (SUM(CASE WHEN qat.is_correct = 1 THEN 1.0 ELSE 0 END) / COUNT(qat.id)) ASC
        LIMIT 5
    ''', (attempt_id,)).fetchall()

    return render_template('results.html',
        attempt=attempt, questions=questions, breakdown=breakdown,
        mock_result=mock_result, weak_topics=weak_topics)


@app.route('/mock-tests')
def mock_tests():
    db = get_db()
    tests = db.execute('''
        SELECT mt.*,
               (SELECT COUNT(*) FROM quiz_attempts qa WHERE qa.mock_test_id = mt.id AND qa.completed_at IS NOT NULL) as attempts,
               (SELECT MAX(qa.score_percentage) FROM quiz_attempts qa WHERE qa.mock_test_id = mt.id AND qa.completed_at IS NOT NULL) as best_score
        FROM mock_tests mt
        ORDER BY mt.id DESC
    ''').fetchall()

    # Score progression for chart
    score_history = db.execute('''
        SELECT qa.id, qa.score_percentage, qa.completed_at, mt.name
        FROM quiz_attempts qa
        JOIN mock_tests mt ON qa.mock_test_id = mt.id
        WHERE qa.completed_at IS NOT NULL AND qa.quiz_type = 'mock_test'
        ORDER BY qa.completed_at
    ''').fetchall()

    return render_template('mock_tests.html', tests=tests, score_history=score_history)


@app.route('/mock-test/<int:test_id>')
def take_mock_test(test_id):
    db = get_db()
    test = db.execute("SELECT * FROM mock_tests WHERE id = ?", (test_id,)).fetchone()

    questions = db.execute('''
        SELECT q.*, mtq.question_order, mtq.section
        FROM mock_test_questions mtq
        JOIN questions q ON mtq.question_id = q.id
        WHERE mtq.mock_test_id = ?
        ORDER BY mtq.question_order
    ''', (test_id,)).fetchall()

    # Create attempt
    db.execute('''
        INSERT INTO quiz_attempts (quiz_type, mock_test_id, total_questions)
        VALUES ('mock_test', ?, ?)
    ''', (test_id, len(questions)))
    attempt_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.commit()

    return render_template('mock_test.html',
        test=test, questions=questions, attempt_id=attempt_id)


@app.route('/analytics')
def analytics():
    db = get_db()

    # Overall progress over time
    daily_stats = db.execute('''
        SELECT DATE(attempted_at) as day,
               COUNT(*) as total,
               SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END) as correct
        FROM question_attempts
        GROUP BY DATE(attempted_at)
        ORDER BY day DESC
        LIMIT 30
    ''').fetchall()

    # Subject-wise performance
    subject_stats = db.execute('''
        SELECT s.name, s.icon, s.color,
               COUNT(DISTINCT q.id) as total_questions,
               COUNT(DISTINCT qa.question_id) as attempted,
               SUM(CASE WHEN qa.is_correct = 1 THEN 1 ELSE 0 END) as correct
        FROM subjects s
        LEFT JOIN topics t ON t.subject_id = s.id
        LEFT JOIN questions q ON q.topic_id = t.id
        LEFT JOIN question_attempts qa ON qa.question_id = q.id
        GROUP BY s.id
        ORDER BY s.name
    ''').fetchall()

    # Weak topics (lowest accuracy with at least 5 attempts)
    weak_topics = db.execute('''
        SELECT t.name as topic_name, s.name as subject_name, s.icon,
               COUNT(qa.id) as attempts,
               SUM(CASE WHEN qa.is_correct = 1 THEN 1 ELSE 0 END) as correct,
               ROUND(SUM(CASE WHEN qa.is_correct = 1 THEN 1.0 ELSE 0 END) / COUNT(qa.id) * 100, 1) as accuracy
        FROM topics t
        JOIN subjects s ON t.subject_id = s.id
        JOIN questions q ON q.topic_id = t.id
        JOIN question_attempts qa ON qa.question_id = q.id
        GROUP BY t.id
        HAVING COUNT(qa.id) >= 5
        ORDER BY accuracy ASC
        LIMIT 10
    ''').fetchall()

    # Quiz history
    quiz_history = db.execute('''
        SELECT qa.*, t.name as topic_name, s.name as subject_name, s.icon, mt.name as test_name
        FROM quiz_attempts qa
        LEFT JOIN topics t ON qa.topic_id = t.id
        LEFT JOIN subjects s ON t.subject_id = s.id
        LEFT JOIN mock_tests mt ON qa.mock_test_id = mt.id
        WHERE qa.completed_at IS NOT NULL
        ORDER BY qa.completed_at DESC
        LIMIT 50
    ''').fetchall()

    # Total study time
    total_time = db.execute('''
        SELECT COALESCE(SUM(time_taken_seconds), 0) as total
        FROM quiz_attempts
        WHERE completed_at IS NOT NULL
    ''').fetchone()['total']

    return render_template('analytics.html',
        daily_stats=daily_stats,
        subject_stats=subject_stats,
        weak_topics=weak_topics,
        quiz_history=quiz_history,
        total_time=total_time
    )


@app.route('/api/bookmark', methods=['POST'])
def toggle_bookmark():
    data = request.json
    db = get_db()
    question_id = data['question_id']

    existing = db.execute("SELECT id FROM bookmarks WHERE question_id = ?", (question_id,)).fetchone()
    if existing:
        db.execute("DELETE FROM bookmarks WHERE question_id = ?", (question_id,))
        db.commit()
        return jsonify({'bookmarked': False})
    else:
        db.execute("INSERT INTO bookmarks (question_id, notes) VALUES (?, ?)",
                   (question_id, data.get('notes', '')))
        db.commit()
        return jsonify({'bookmarked': True})


@app.route('/bookmarks')
def bookmarks():
    db = get_db()
    bookmarked = db.execute('''
        SELECT b.*, q.question_text, q.passage, q.option_a, q.option_b, q.option_c, q.option_d,
               q.correct_answer, q.explanation, t.name as topic_name, s.name as subject_name, s.icon
        FROM bookmarks b
        JOIN questions q ON b.question_id = q.id
        JOIN topics t ON q.topic_id = t.id
        JOIN subjects s ON t.subject_id = s.id
        ORDER BY b.created_at DESC
    ''').fetchall()

    return render_template('bookmarks.html', bookmarks=bookmarked)


@app.route('/weak-areas')
def weak_areas():
    """Practice weak areas - questions you got wrong."""
    db = get_db()

    questions = db.execute('''
        SELECT DISTINCT q.*, t.name as topic_name, s.name as subject_name, s.icon, s.color
        FROM questions q
        JOIN topics t ON q.topic_id = t.id
        JOIN subjects s ON t.subject_id = s.id
        JOIN question_attempts qa ON qa.question_id = q.id
        WHERE qa.is_correct = 0
        AND q.correct_answer IS NOT NULL AND q.correct_answer != ''
        AND q.id NOT IN (
            SELECT question_id FROM question_attempts
            WHERE is_correct = 1
            AND attempted_at > (
                SELECT MAX(attempted_at) FROM question_attempts qa2
                WHERE qa2.question_id = q.id AND qa2.is_correct = 0
            )
        )
        ORDER BY RANDOM()
        LIMIT 20
    ''').fetchall()

    if not questions:
        return redirect(url_for('dashboard'))

    db.execute('''
        INSERT INTO quiz_attempts (quiz_type, total_questions)
        VALUES ('weak_areas', ?)
    ''', (len(questions),))
    attempt_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.commit()

    topic = {'name': 'Weak Areas Review', 'subject_name': 'Mixed', 'icon': '🎯', 'color': '#ef4444'}
    return render_template('quiz.html',
        topic=topic, questions=questions, attempt_id=attempt_id)


@app.route('/api/reset_data', methods=['POST'])
def reset_data():
    """Reset all progress data (keep questions)."""
    db = get_db()
    db.execute("DELETE FROM question_attempts")
    db.execute("DELETE FROM quiz_attempts")
    db.execute("DELETE FROM bookmarks")
    db.execute("DELETE FROM study_sessions")
    db.commit()
    return jsonify({'status': 'ok'})


# ---------------------------------------------------------------------------
# MH-CET 2025+ FORMAT: 120 MCQs, 120 minutes
# Section distribution: English(40), GK(32), Legal(24), Logical(24)
# ---------------------------------------------------------------------------

SECTION_DISTRIBUTION = {
    'English': 40,
    'General Knowledge': 32,
    'Legal Reasoning': 24,
    'Logical Reasoning': 24,
}

SECTION_SHORT = {
    'English': 'English',
    'General Knowledge': 'GK',
    'Legal Reasoning': 'Legal',
    'Logical Reasoning': 'Logical',
}


def _pull_questions_for_subject(db, subject_name, count):
    """Pull random questions for a subject, with valid options and answer."""
    rows = db.execute('''
        SELECT q.id FROM questions q
        JOIN topics t ON q.topic_id = t.id
        JOIN subjects s ON t.subject_id = s.id
        WHERE s.name = ?
          AND q.option_a != '' AND q.option_b != ''
          AND q.correct_answer IS NOT NULL AND q.correct_answer != ''
        ORDER BY RANDOM()
        LIMIT ?
    ''', (subject_name, count)).fetchall()
    return [r['id'] for r in rows]


def _create_mock_test_from_ids(db, name, question_ids_by_section, time_minutes):
    """Create a mock_test + mock_test_questions from section-mapped question IDs."""
    total = sum(len(ids) for ids in question_ids_by_section.values())
    db.execute(
        "INSERT INTO mock_tests (name, total_questions, time_limit_minutes, source) VALUES (?, ?, ?, ?)",
        (name, total, time_minutes, 'generated')
    )
    mt_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

    order = 1
    for section, qids in question_ids_by_section.items():
        for qid in qids:
            db.execute('''
                INSERT INTO mock_test_questions (mock_test_id, question_id, question_order, section)
                VALUES (?, ?, ?, ?)
            ''', (mt_id, qid, order, section))
            order += 1

    db.commit()
    return mt_id


@app.route('/generate-mock', methods=['POST'])
def generate_mock():
    """Generate a full 120-question mock test with proper section distribution."""
    db = get_db()
    question_ids = {}
    for subj, count in SECTION_DISTRIBUTION.items():
        ids = _pull_questions_for_subject(db, subj, count)
        if ids:
            question_ids[subj] = ids

    total = sum(len(v) for v in question_ids.values())
    if total == 0:
        return redirect(url_for('mock_tests'))

    # Name with sequential number
    existing = db.execute(
        "SELECT COUNT(*) FROM mock_tests WHERE source = 'generated'"
    ).fetchone()[0]
    name = f"Full Mock Test #{existing + 1}"

    mt_id = _create_mock_test_from_ids(db, name, question_ids, 120)
    return redirect(url_for('take_mock_test', test_id=mt_id))


@app.route('/generate-sectional/<subject_name>', methods=['POST'])
def generate_sectional(subject_name):
    """Generate a sectional test for one subject."""
    db = get_db()
    count = SECTION_DISTRIBUTION.get(subject_name, 24)
    ids = _pull_questions_for_subject(db, subject_name, count)
    if not ids:
        return redirect(url_for('mock_tests'))

    # Time proportional: 1 min per question
    time_minutes = len(ids)

    existing = db.execute(
        "SELECT COUNT(*) FROM mock_tests WHERE source = 'generated' AND name LIKE ?",
        (f'%{SECTION_SHORT.get(subject_name, subject_name)}%',)
    ).fetchone()[0]
    name = f"{SECTION_SHORT.get(subject_name, subject_name)} Sectional #{existing + 1}"

    mt_id = _create_mock_test_from_ids(db, name, {subject_name: ids}, time_minutes)
    return redirect(url_for('take_mock_test', test_id=mt_id))


@app.route('/generate-adaptive', methods=['POST'])
def generate_adaptive():
    """Generate an adaptive test focusing on weak topics."""
    db = get_db()

    # Find weak topics: lowest accuracy with at least 3 attempts
    weak = db.execute('''
        SELECT t.id as topic_id, s.name as subject_name,
               COUNT(qa.id) as attempts,
               SUM(CASE WHEN qa.is_correct = 1 THEN 1.0 ELSE 0 END) / COUNT(qa.id) as accuracy
        FROM topics t
        JOIN subjects s ON t.subject_id = s.id
        JOIN questions q ON q.topic_id = t.id
        JOIN question_attempts qa ON qa.question_id = q.id
        WHERE s.name IN ('English', 'General Knowledge', 'Legal Reasoning', 'Logical Reasoning')
        GROUP BY t.id
        HAVING COUNT(qa.id) >= 3
        ORDER BY accuracy ASC
        LIMIT 20
    ''').fetchall()

    question_ids = {}
    target_total = 60  # Shorter adaptive test

    if weak:
        # Distribute 60 questions across weak topics, more from weaker ones
        per_topic = max(3, target_total // len(weak))
        collected = 0
        for row in weak:
            if collected >= target_total:
                break
            subj = row['subject_name']
            ids = db.execute('''
                SELECT q.id FROM questions q
                WHERE q.topic_id = ?
                  AND q.option_a != '' AND q.option_b != ''
                  AND q.correct_answer IS NOT NULL AND q.correct_answer != ''
                ORDER BY RANDOM()
                LIMIT ?
            ''', (row['topic_id'], per_topic)).fetchall()
            ids = [r['id'] for r in ids]
            if ids:
                question_ids.setdefault(subj, []).extend(ids)
                collected += len(ids)
    else:
        # No attempt data, just do a balanced 60-question test
        for subj, count in SECTION_DISTRIBUTION.items():
            ids = _pull_questions_for_subject(db, subj, count // 2)
            if ids:
                question_ids[subj] = ids

    total = sum(len(v) for v in question_ids.values())
    if total == 0:
        return redirect(url_for('mock_tests'))

    existing = db.execute(
        "SELECT COUNT(*) FROM mock_tests WHERE source = 'generated' AND name LIKE '%Adaptive%'"
    ).fetchone()[0]
    name = f"Adaptive Test #{existing + 1}"

    mt_id = _create_mock_test_from_ids(db, name, question_ids, total)
    return redirect(url_for('take_mock_test', test_id=mt_id))


# ---------------------------------------------------------------------------
# ENHANCED API ROUTES
# ---------------------------------------------------------------------------

@app.route('/api/dashboard_stats')
def dashboard_stats():
    """Return JSON with comprehensive dashboard statistics."""
    db = get_db()

    # Overall accuracy
    overall = db.execute('''
        SELECT COUNT(*) as total,
               SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END) as correct
        FROM question_attempts
    ''').fetchone()
    overall_accuracy = round((overall['correct'] or 0) / overall['total'] * 100, 1) if overall['total'] else 0

    # Section-wise accuracy
    section_stats = db.execute('''
        SELECT s.name,
               COUNT(qa.id) as attempts,
               SUM(CASE WHEN qa.is_correct = 1 THEN 1 ELSE 0 END) as correct
        FROM subjects s
        JOIN topics t ON t.subject_id = s.id
        JOIN questions q ON q.topic_id = t.id
        JOIN question_attempts qa ON qa.question_id = q.id
        WHERE s.name IN ('English', 'General Knowledge', 'Legal Reasoning', 'Logical Reasoning')
        GROUP BY s.id
    ''').fetchall()
    sections = {}
    for row in section_stats:
        acc = round(row['correct'] / row['attempts'] * 100, 1) if row['attempts'] else 0
        sections[row['name']] = {
            'attempts': row['attempts'],
            'correct': row['correct'],
            'accuracy': acc
        }

    # Weak topics
    weak = db.execute('''
        SELECT t.name as topic, s.name as subject,
               COUNT(qa.id) as attempts,
               ROUND(SUM(CASE WHEN qa.is_correct = 1 THEN 1.0 ELSE 0 END) / COUNT(qa.id) * 100, 1) as accuracy
        FROM topics t
        JOIN subjects s ON t.subject_id = s.id
        JOIN questions q ON q.topic_id = t.id
        JOIN question_attempts qa ON qa.question_id = q.id
        GROUP BY t.id
        HAVING COUNT(qa.id) >= 5
        ORDER BY accuracy ASC
        LIMIT 10
    ''').fetchall()
    weak_topics = [{'topic': r['topic'], 'subject': r['subject'],
                    'attempts': r['attempts'], 'accuracy': r['accuracy']} for r in weak]

    # Mock test score progression
    mock_scores = db.execute('''
        SELECT qa.id, qa.score_percentage, qa.completed_at, mt.name
        FROM quiz_attempts qa
        JOIN mock_tests mt ON qa.mock_test_id = mt.id
        WHERE qa.completed_at IS NOT NULL AND qa.quiz_type = 'mock_test'
        ORDER BY qa.completed_at
    ''').fetchall()
    progression = [{'id': r['id'], 'score': r['score_percentage'],
                    'date': r['completed_at'], 'name': r['name']} for r in mock_scores]

    # Daily question count (last 30 days)
    daily = db.execute('''
        SELECT DATE(attempted_at) as day, COUNT(*) as count
        FROM question_attempts
        WHERE attempted_at >= DATE('now', '-30 days')
        GROUP BY DATE(attempted_at)
        ORDER BY day
    ''').fetchall()
    daily_counts = [{'date': r['day'], 'count': r['count']} for r in daily]

    return jsonify({
        'overall_accuracy': overall_accuracy,
        'sections': sections,
        'weak_topics': weak_topics,
        'mock_progression': progression,
        'daily_counts': daily_counts
    })


# ---------------------------------------------------------------------------
# PHASE 7 — ENHANCED UX ROUTES
# ---------------------------------------------------------------------------

@app.route('/api/streak')
def get_streak():
    """Calculate current study streak in days."""
    db = get_db()
    days = db.execute('''
        SELECT DISTINCT DATE(attempted_at) as day
        FROM question_attempts
        ORDER BY day DESC
        LIMIT 60
    ''').fetchall()
    day_set = {r['day'] for r in days}
    streak = 0
    check = datetime.now().date()
    while check.isoformat() in day_set:
        streak += 1
        check -= timedelta(days=1)
    return jsonify({'streak': streak, 'days': list(day_set)[:30]})


@app.route('/revision')
def revision_mode():
    """Revision Mode — show only bookmarked questions in quiz format."""
    db = get_db()
    questions = db.execute('''
        SELECT q.*, t.name as topic_name, s.name as subject_name, s.icon, s.color
        FROM bookmarks b
        JOIN questions q ON b.question_id = q.id
        JOIN topics t ON q.topic_id = t.id
        JOIN subjects s ON t.subject_id = s.id
        ORDER BY RANDOM()
        LIMIT 40
    ''').fetchall()
    if not questions:
        return render_template('revision.html', questions=[], message="No bookmarks yet. Bookmark questions during tests to review them here.")
    db.execute("INSERT INTO quiz_attempts (quiz_type, total_questions) VALUES ('revision', ?)", (len(questions),))
    attempt_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.commit()
    topic = {'name': 'Revision Mode', 'subject_name': 'Bookmarked', 'icon': '🔖', 'color': '#8b5cf6'}
    return render_template('quiz.html', topic=topic, questions=questions, attempt_id=attempt_id)


@app.route('/study-plan')
def study_plan():
    """Show the complete MH-CET Law study plan."""
    plan_path = os.path.join(os.path.dirname(__file__), '24_day_study_plan.json')
    plan = []
    if os.path.exists(plan_path):
        with open(plan_path) as f:
            plan = json.load(f)
    today = datetime.now().strftime('%b %d, %Y')
    db = get_db()
    rows = db.execute(
        "SELECT DISTINCT mock_test_id FROM quiz_attempts WHERE mock_test_id IS NOT NULL AND completed_at IS NOT NULL"
    ).fetchall()
    completed_test_ids = {r['mock_test_id'] for r in rows}
    return render_template('study_plan.html', plan=plan, today=today, completed_test_ids=completed_test_ids)


@app.route('/api/post_test_analytics/<int:attempt_id>')
def post_test_analytics(attempt_id):
    """Detailed per-question analytics for a completed test."""
    db = get_db()
    questions = db.execute('''
        SELECT qat.question_id, qat.is_correct, qat.answer_given, qat.time_taken_seconds,
               q.question_text, q.option_a, q.option_b, q.option_c, q.option_d,
               q.correct_answer, q.explanation, q.difficulty,
               t.name as topic_name, s.name as subject_name
        FROM question_attempts qat
        JOIN questions q ON qat.question_id = q.id
        JOIN topics t ON q.topic_id = t.id
        JOIN subjects s ON t.subject_id = s.id
        WHERE qat.quiz_attempt_id = ?
        ORDER BY qat.id
    ''', (attempt_id,)).fetchall()

    per_subject = {}
    slow_questions = []  # > 90 seconds
    wrong_questions = []

    for q in questions:
        subj = q['subject_name']
        if subj not in per_subject:
            per_subject[subj] = {'total': 0, 'correct': 0, 'time': 0}
        per_subject[subj]['total'] += 1
        per_subject[subj]['time'] += (q['time_taken_seconds'] or 0)
        if q['is_correct']:
            per_subject[subj]['correct'] += 1
        else:
            wrong_questions.append(dict(q))
        if (q['time_taken_seconds'] or 0) > 90:
            slow_questions.append(dict(q))

    # Cutoff comparison
    attempt = db.execute("SELECT score_percentage FROM quiz_attempts WHERE id = ?", (attempt_id,)).fetchone()
    score = (attempt['score_percentage'] if attempt else 0) or 0
    cutoff_data = {
        'your_score_pct': score,
        'glc_cutoff_pct': 91.7,   # 110/120
        'kc_law_cutoff_pct': 83.3, # 100/120
        'glc_gap': round(91.7 - score, 1),
        'kc_gap': round(83.3 - score, 1),
    }

    return jsonify({
        'per_subject': per_subject,
        'slow_questions': slow_questions[:5],
        'wrong_questions': wrong_questions[:20],
        'cutoff_comparison': cutoff_data,
        'total_wrong': len(wrong_questions),
        'avg_time': round(sum(q['time_taken_seconds'] or 0 for q in questions) / len(questions), 1) if questions else 0,
    })


@app.route('/heatmap')
def topic_heatmap():
    """Weak topic heatmap — color-coded by accuracy."""
    db = get_db()
    topic_data = db.execute('''
        SELECT t.id, t.name as topic_name, s.name as subject_name, s.color,
               COUNT(qa.id) as attempts,
               ROUND(SUM(CASE WHEN qa.is_correct = 1 THEN 1.0 ELSE 0 END) / COUNT(qa.id) * 100, 1) as accuracy
        FROM topics t
        JOIN subjects s ON t.subject_id = s.id
        JOIN questions q ON q.topic_id = t.id
        LEFT JOIN question_attempts qa ON qa.question_id = q.id
        GROUP BY t.id
        ORDER BY s.name, accuracy ASC
    ''').fetchall()

    # Group by subject
    heatmap = {}
    for row in topic_data:
        subj = row['subject_name']
        if subj not in heatmap:
            heatmap[subj] = []
        acc = row['accuracy'] or 0
        if acc == 0 and (row['attempts'] or 0) == 0:
            color_class = 'untested'
        elif acc >= 80:
            color_class = 'strong'
        elif acc >= 60:
            color_class = 'moderate'
        elif acc >= 40:
            color_class = 'weak'
        else:
            color_class = 'critical'
        heatmap[subj].append({
            'topic': row['topic_name'],
            'accuracy': acc,
            'attempts': row['attempts'] or 0,
            'color_class': color_class,
        })

    return render_template('heatmap.html', heatmap=heatmap)


@app.route('/api/daily_plan_progress', methods=['POST'])
def update_plan_progress():
    """Mark a daily plan task as completed."""
    data = request.json
    db = get_db()
    db.execute("""
        UPDATE daily_plan SET status = 'completed', completed_questions = ?
        WHERE plan_date = ? AND task_type = ?
    """, (data.get('completed', 0), data['date'], data['task_type']))
    db.commit()
    return jsonify({'ok': True})


# ---------------------------------------------------------------------------
# QA / ADMIN ROUTES
# ---------------------------------------------------------------------------

@app.route('/api/report-wrong-answer', methods=['POST'])
def report_wrong_answer():
    data = request.get_json(force=True)
    qid = data.get('question_id')
    context = data.get('context', '')
    if not qid:
        return jsonify({'ok': False, 'error': 'missing question_id'}), 400
    db = get_db()
    db.execute(
        "INSERT INTO wrong_answer_reports (question_id, context) VALUES (?, ?)",
        (qid, context[:500])
    )
    db.commit()
    return jsonify({'ok': True, 'message': 'Reported. Thank you!'})


@app.route('/admin/qa-report')
def admin_qa_report():
    import os
    db = get_db()
    total = db.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    validated = db.execute("SELECT COUNT(*) FROM questions WHERE is_validated=1").fetchone()[0]
    fixed = db.execute(
        "SELECT COUNT(*) FROM questions WHERE validation_note LIKE 'corrected%'"
    ).fetchone()[0]
    confirmed = db.execute(
        "SELECT COUNT(*) FROM questions WHERE validation_note='confirmed_correct'"
    ).fetchone()[0]
    skipped = db.execute(
        "SELECT COUNT(*) FROM questions WHERE validation_note='low_confidence_skipped'"
    ).fetchone()[0]
    reports = db.execute(
        "SELECT COUNT(DISTINCT question_id) FROM wrong_answer_reports"
    ).fetchone()[0]

    corrections = db.execute("""
        SELECT q.id, q.question_text, q.correct_answer, q.validation_note,
               q.explanation, s.name as subject_name
        FROM questions q
        LEFT JOIN topics t ON q.topic_id=t.id
        LEFT JOIN subjects s ON t.subject_id=s.id
        WHERE q.validation_note LIKE 'corrected%'
        ORDER BY q.id DESC
        LIMIT 200
    """).fetchall()

    log_path = os.path.join(os.path.dirname(__file__), 'qa_report.json')
    qa_json = {}
    if os.path.exists(log_path):
        try:
            with open(log_path) as f:
                qa_json = json.load(f)
        except Exception:
            pass

    agent_running = False
    pid_path = os.path.join(os.path.dirname(__file__), 'qa_agent.pid')
    if os.path.exists(pid_path):
        try:
            with open(pid_path) as f:
                pid = int(f.read().strip())
            os.kill(pid, 0)
            agent_running = True
        except Exception:
            agent_running = False

    return render_template('admin_qa.html',
        total=total, validated=validated, fixed=fixed,
        confirmed=confirmed, skipped=skipped, reports=reports,
        corrections=corrections, qa_json=qa_json,
        agent_running=agent_running,
        pct=round(validated / total * 100) if total else 0
    )


@app.route('/admin/run-qa', methods=['POST'])
def admin_run_qa():
    import subprocess, os
    script = os.path.join(os.path.dirname(__file__), 'qa_agent.py')
    log_file = os.path.join(os.path.dirname(__file__), 'qa_agent.log')
    pid_file = os.path.join(os.path.dirname(__file__), 'qa_agent.pid')

    # Check if already running
    if os.path.exists(pid_file):
        try:
            with open(pid_file) as f:
                pid = int(f.read().strip())
            os.kill(pid, 0)
            return jsonify({'ok': False, 'message': f'Agent already running (PID {pid})'})
        except Exception:
            pass

    with open(log_file, 'a') as lf:
        proc = subprocess.Popen(
            ['python3', script],
            stdout=lf, stderr=lf,
            start_new_session=True
        )
    with open(pid_file, 'w') as f:
        f.write(str(proc.pid))

    return jsonify({'ok': True, 'message': f'QA Agent started (PID {proc.pid})', 'pid': proc.pid})


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    print("=" * 60)
    print("  MH-CET Law 2027 - Learning Portal")
    print("=" * 60)

    init_db()
    load_data_from_pdfs()

    print("\nStarting server...")
    print("Open http://127.0.0.1:5050 in your browser")
    print("=" * 60)

    app.run(debug=True, port=5050)
