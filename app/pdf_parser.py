"""
PDF Parser for MH-CET Law 2027 Study Materials
Extracts questions, options, answers, and solutions from PDF books.
"""

import re
import os
import pdfplumber


def extract_text_from_pages(pdf_path, start_page, end_page):
    """Extract text from a range of pages (1-indexed)."""
    texts = []
    with pdfplumber.open(pdf_path) as pdf:
        for i in range(start_page - 1, min(end_page, len(pdf.pages))):
            page = pdf.pages[i]
            text = page.extract_text()
            if text:
                texts.append(text)
    return "\n".join(texts)


def clean_text(text):
    """Clean extracted text."""
    text = text.replace("www.careers360.com", "")
    text = re.sub(r'Back to Index\s*\d*', '', text)
    text = re.sub(r'Answer\s*\d+', '', text)
    text = re.sub(r'Solutions\s*\d+', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


# ---------------------------------------------------------------------------
# MATHS PDF PARSER
# ---------------------------------------------------------------------------

def parse_maths_pdf(pdf_path):
    """Parse Maths Practice Questions PDF into structured questions."""
    questions = []

    # Extract question pages (pages 8-37)
    q_text = extract_text_from_pages(pdf_path, 8, 37)
    q_text = clean_text(q_text)

    # Extract answer key (pages 39-40)
    ak_text = extract_text_from_pages(pdf_path, 39, 40)

    # Extract solutions (pages 41-71)
    sol_text = extract_text_from_pages(pdf_path, 41, 71)
    sol_text = clean_text(sol_text)

    # Parse answer keys
    answer_map = parse_maths_answer_key(ak_text)

    # Parse solutions
    solution_map = parse_maths_solutions(sol_text)

    # Parse questions by SET
    set_blocks = re.split(r'SET\s*-\s*(\d+)', q_text)
    # set_blocks: ['', '1', '<set1 text>', '2', '<set2 text>', ...]

    for i in range(1, len(set_blocks) - 1, 2):
        set_num = int(set_blocks[i])
        set_text = set_blocks[i + 1]

        set_questions = parse_mcq_block(set_text)

        for idx, q in enumerate(set_questions, 1):
            q['topic'] = 'Mathematics'
            q['subject'] = 'Mathematics'
            q['set_num'] = set_num
            q['source'] = 'Maths Practice Questions'

            key = (set_num, idx)
            if key in answer_map:
                q['correct_answer'] = answer_map[key]
            if key in solution_map:
                q['explanation'] = solution_map[key]

            questions.append(q)

    return questions


def parse_maths_answer_key(text):
    """Parse grid-style answer key for maths sets."""
    answer_map = {}
    current_set = 0
    lines = text.strip().split('\n')

    for i, line in enumerate(lines):
        set_match = re.search(r'SET\s*(\d+)', line)
        if set_match:
            current_set = int(set_match.group(1))
            continue

        # Look for number row followed by answer row
        nums = re.findall(r'\d+', line)
        if nums and all(1 <= int(n) <= 10 for n in nums) and len(nums) >= 5:
            # Next line should be answers
            if i + 1 < len(lines):
                answers = re.findall(r'[A-D]', lines[i + 1])
                for j, ans in enumerate(answers):
                    q_num = int(nums[j]) if j < len(nums) else j + 1
                    answer_map[(current_set, q_num)] = ans

    return answer_map


def parse_maths_solutions(text):
    """Parse solutions section for maths."""
    solution_map = {}
    # Split by SET headers
    set_blocks = re.split(r'SET\s*-\s*(\d+)', text)

    for i in range(1, len(set_blocks) - 1, 2):
        set_num = int(set_blocks[i])
        block = set_blocks[i + 1]

        # Split by question number pattern: "1-B" or "1-A"
        parts = re.split(r'(\d+)-([A-D])', block)
        for j in range(1, len(parts) - 2, 3):
            q_num = int(parts[j])
            explanation = parts[j + 2].strip()
            # Clean up explanation
            explanation = re.sub(r'_{2,}', '', explanation).strip()
            if explanation:
                solution_map[(set_num, q_num)] = explanation

    return solution_map


# ---------------------------------------------------------------------------
# GENERIC MCQ PARSER
# ---------------------------------------------------------------------------

def parse_mcq_block(text):
    """Parse a block of text into MCQ questions with options."""
    questions = []
    last_passage = ''  # Carry passage forward for multi-question passages

    # Split by question markers: Q1., Q2., etc. or just Q1, Q2 etc.
    parts = re.split(r'Q(\d+)\s*[.\s]', text)
    # parts: ['<preamble>', '1', '<q1 text>', '2', '<q2 text>', ...]

    for i in range(1, len(parts) - 1, 2):
        q_num = int(parts[i])
        q_body = parts[i + 1].strip()

        q = extract_question_and_options(q_body)
        if q:
            q['question_num'] = q_num

            # If this question has a substantial passage, remember it
            if q['passage'] and len(q['passage']) > 100:
                last_passage = q['passage']
            # If question references "passage" but has no passage, use the last one
            elif not q['passage'] and last_passage:
                q_lower = q['question_text'].lower()
                if any(kw in q_lower for kw in ['passage', 'paragraph', 'above', 'given text', 'the text']):
                    q['passage'] = last_passage

            questions.append(q)

    return questions


def extract_question_and_options(text):
    """Extract question text, passage, and options from a question block."""
    # Try multiple option patterns
    option_patterns = [
        # A) B) C) D) pattern
        r'([A-D])\)\s*(.+?)(?=(?:[A-D]\)|$))',
        # (a) (b) (c) (d) pattern
        r'\(([a-dA-D])\)\s*(.+?)(?=(?:\([a-dA-D]\)|$))',
    ]

    options = {}
    question_text = text
    option_start = len(text)

    # Try to find options with A) B) C) D) — also match inline like "A)10"
    opt_matches = list(re.finditer(r'(?:^|\n)\s*([A-D])\)', text, re.MULTILINE))
    if not opt_matches:
        # Try A] B] C] D] pattern
        opt_matches = list(re.finditer(r'(?:^|\n)\s*([A-D])\]', text, re.MULTILINE))
    if not opt_matches:
        # Try (A) (B) (C) (D) or (a) (b) (c) (d)
        opt_matches = list(re.finditer(r'(?:^|\n)\s*\(([a-dA-D])\)\s*', text, re.MULTILINE))
    if not opt_matches:
        # Try lowercase a) b) c) d)
        opt_matches = list(re.finditer(r'(?:^|\n)\s*([a-d])\)\s*', text, re.MULTILINE))

    if len(opt_matches) >= 2:
        option_start = opt_matches[0].start()
        for j, m in enumerate(opt_matches):
            letter = m.group(1).upper()
            # Option text starts right after the match (skip `)` or `]` or `) `)
            raw_end = m.end()
            # For A) or A] pattern, skip the closing bracket if not already past it
            remaining = text[raw_end:]
            if remaining and remaining[0] in ')]:':
                raw_end += 1
            # Skip whitespace
            while raw_end < len(text) and text[raw_end] == ' ':
                raw_end += 1
            start = raw_end
            end = opt_matches[j + 1].start() if j + 1 < len(opt_matches) else len(text)
            opt_text = text[start:end].strip()
            # Clean trailing stuff
            opt_text = re.sub(r'\n.*Therefore.*$', '', opt_text, flags=re.DOTALL).strip()
            opt_text = re.sub(r'\n.*Hence.*$', '', opt_text, flags=re.DOTALL).strip()
            # Remove answer key data that leaked into options
            opt_text = re.sub(r'Answer Key.*$', '', opt_text, flags=re.DOTALL).strip()
            opt_text = re.sub(r'ANSWER KEY.*$', '', opt_text, flags=re.DOTALL).strip()
            opt_text = re.sub(r'\n\s*\d+\s+\d+\s+\d+\s+\d+\s+\d+.*$', '', opt_text, flags=re.DOTALL).strip()
            # Remove solution data
            opt_text = re.sub(r'\nSOLUTIONS.*$', '', opt_text, flags=re.DOTALL).strip()
            opt_text = re.sub(r'\n\d+-[A-D]\n.*$', '', opt_text, flags=re.DOTALL).strip()
            # Remove "www.careers360" lines
            opt_text = re.sub(r'\n?www\.careers360.*$', '', opt_text, flags=re.DOTALL).strip()
            # Truncate overly long options (likely parsing artifacts)
            if len(opt_text) > 300:
                # Find a natural break point
                for cutoff in ['. ', '\n']:
                    pos = opt_text.find(cutoff, 50)
                    if 50 < pos < 200:
                        opt_text = opt_text[:pos + 1].strip()
                        break
                else:
                    opt_text = opt_text[:200].strip()
            options[letter] = opt_text

    question_text = text[:option_start].strip()
    if not question_text or not options:
        return None

    # Try to separate passage from question
    passage = ''
    actual_question = question_text

    # Check for passage indicators
    passage_markers = [
        r'(Read the (?:passage|following).*?(?:answer the question|question that follow).*?\n)',
        r'(PRINCIPLE:.*?)(?:FACTS:|Factual Situation:)',
    ]

    for marker in passage_markers:
        m = re.search(marker, question_text, re.DOTALL | re.IGNORECASE)
        if m:
            break

    # If text is long and has a clear question at the end, split it
    lines = question_text.split('\n')
    if len(lines) > 3:
        # Look for "Question" or "Decide" markers
        for k, line in enumerate(lines):
            if re.match(r'^\s*(Question|Decide|What|Which|Who|How|Why|Can |Is |Are |Does |Do |Should |Would )', line, re.IGNORECASE):
                if k > 1:
                    passage = '\n'.join(lines[:k]).strip()
                    actual_question = '\n'.join(lines[k:]).strip()
                    break

    if not passage:
        # For principle-fact questions
        pf = re.split(r'(FACTS?:|Factual Situation:)', question_text, maxsplit=1, flags=re.IGNORECASE)
        if len(pf) >= 3:
            passage = question_text
            actual_question = question_text

    return {
        'passage': passage,
        'question_text': actual_question,
        'option_a': options.get('A', ''),
        'option_b': options.get('B', ''),
        'option_c': options.get('C', ''),
        'option_d': options.get('D', ''),
        'correct_answer': '',
        'explanation': '',
    }


# ---------------------------------------------------------------------------
# LEGAL REASONING PDF PARSER
# ---------------------------------------------------------------------------

LEGAL_TOPICS = [
    ('Contract Law', 6, 134),
    ('Law of Torts', 135, 253),
    ('Criminal Law', 254, 297),
    ('Arbitration & ADR', 298, 312),
    ('Jurisprudence', 313, 334),
    ('Property Law', 335, 345),
    ('Cyber Law', 346, 353),
    ('Environment Law', 354, 362),
    ('Consumer Protection Law', 363, 369),
    ('Family Law', 370, 395),
]

# The PDF contains a second copy with some unique/expanded questions
LEGAL_TOPICS_SECOND_HALF = [
    ('Contract Law', 401, 520),
    ('Law of Torts', 528, 648),
    ('Criminal Law', 649, 692),
    ('Arbitration & ADR', 693, 707),
    ('Jurisprudence', 708, 729),
    ('Property Law', 730, 740),
    ('Cyber Law', 741, 757),
    ('Consumer Protection Law', 758, 764),
    ('Family Law', 765, 791),
]


def parse_legal_reasoning_pdf(pdf_path):
    """Parse Legal Reasoning Practice Questions PDF."""
    import hashlib
    questions = []
    seen_hashes = set()

    with pdfplumber.open(pdf_path) as pdf:
        total_pages = len(pdf.pages)

    # Parse both halves of the PDF
    all_topic_ranges = LEGAL_TOPICS + LEGAL_TOPICS_SECOND_HALF

    for topic_name, start_page, end_page in all_topic_ranges:
        end_page = min(end_page, total_pages)
        text = extract_text_from_pages(pdf_path, start_page, end_page)
        text = clean_text(text)

        # Remove the topic header
        text = re.sub(r'^' + re.escape(topic_name.upper().replace('&', 'AND')) + r'\s*_{0,}', '', text)
        text = re.sub(r'^[A-Z\s&,]+_{2,}', '', text)

        topic_questions = parse_mcq_block(text)

        for q in topic_questions:
            # Deduplicate by question text + options hash
            dedup_key = (q['question_text'][:80] + q.get('option_a', '')[:30]).lower()
            q_hash = hashlib.md5(dedup_key.encode()).hexdigest()
            if q_hash in seen_hashes:
                continue
            seen_hashes.add(q_hash)

            q['topic'] = topic_name
            q['subject'] = 'Legal Reasoning'
            q['source'] = 'Legal Reasoning Practice Questions'
            questions.append(q)

    # Try to find and assign answers
    _assign_legal_answers_from_solutions(pdf_path, questions)

    return questions


def _assign_legal_answers_from_solutions(pdf_path, questions):
    """Extract answer keys from solution sections and assign to questions."""
    # Answer key page ranges per topic (first half)
    # Format: (topic_name, answer_pages_start, answer_pages_end)
    answer_sections = [
        ('Contract Law', 114, 134),
        ('Law of Torts', 236, 253),
        ('Criminal Law', 282, 297),
        ('Arbitration & ADR', 308, 312),
        ('Jurisprudence', 329, 334),
        ('Property Law', 343, 345),
        ('Cyber Law', 352, 353),
        ('Environment Law', 360, 362),
        ('Consumer Protection Law', 368, 369),
        ('Family Law', 386, 395),
    ]

    # Build answer maps per topic
    topic_answers = {}
    with pdfplumber.open(pdf_path) as pdf:
        for topic_name, start, end in answer_sections:
            answers = {}
            for pg in range(start - 1, min(end, len(pdf.pages))):
                text = pdf.pages[pg].extract_text() or ''
                # Match patterns like "1-A", "2-B", "99-C"
                matches = re.findall(r'(\d+)\s*[-]\s*([A-D])\b', text)
                for qnum, ans in matches:
                    num = int(qnum)
                    if 1 <= num <= 200:
                        answers[num] = ans
            topic_answers[topic_name] = answers

    # Assign answers to questions
    # Group questions by topic and question_num
    topic_q_counter = {}
    for q in questions:
        topic = q.get('topic', '')
        if topic not in topic_q_counter:
            topic_q_counter[topic] = 0
        topic_q_counter[topic] += 1
        q_num = q.get('question_num', topic_q_counter[topic])

        if topic in topic_answers and q_num in topic_answers[topic]:
            q['correct_answer'] = topic_answers[topic][q_num]


# ---------------------------------------------------------------------------
# MOCK TEST PDF PARSER
# ---------------------------------------------------------------------------

def parse_mock_tests_pdf(pdf_path):
    """Parse the 10 Mock Tests PDF."""
    mock_tests = []

    # Page ranges from TOC (1-indexed)
    test_ranges = [
        (1, 12, 58, 59, 61, 99),
        (2, 100, 148, 149, 151, 191),
        (3, 192, 241, 242, 244, 286),
        (4, 287, 328, 329, 331, 370),
        (5, 371, 417, 418, 420, 460),
        (6, 461, 509, 510, 512, 550),
        (7, 551, 599, 600, 602, 644),
        (8, 645, 686, 687, 689, 727),
        (9, 728, 773, 774, 776, 813),
        (10, 814, 858, 859, 861, 901),
    ]

    for test_num, q_start, q_end, ak_start, sol_start, sol_end in test_ranges:
        print(f"  Parsing Mock Test {test_num}...")

        # Extract question text
        q_text = extract_text_from_pages(pdf_path, q_start, q_end)
        q_text = clean_text(q_text)

        # Extract answer key
        ak_text = extract_text_from_pages(pdf_path, ak_start, ak_start + 1)

        # Extract solutions
        sol_text = extract_text_from_pages(pdf_path, sol_start, sol_end)
        sol_text = clean_text(sol_text)

        # Parse answer key (grid format)
        answer_map = parse_mock_answer_key(ak_text)

        # Parse solutions
        solution_map = parse_mock_solutions(sol_text)

        # Parse questions
        questions = parse_mock_questions(q_text, test_num)

        # Assign answers and solutions
        for q in questions:
            q_num = q.get('question_num', 0)
            if q_num in answer_map:
                q['correct_answer'] = answer_map[q_num]
            if q_num in solution_map:
                q['explanation'] = solution_map[q_num]

        # Assign subjects based on question number ranges
        # Mock test pattern: Q1-30 Legal, Q31-70 GK, Q71-100 Logical, Q101-150 English
        for q in questions:
            qn = q.get('question_num', 0)
            if qn <= 30:
                q['subject'] = 'Legal Reasoning'
                q['topic'] = 'Legal Aptitude'
            elif qn <= 70:
                q['subject'] = 'General Knowledge'
                q['topic'] = 'GK & Current Affairs'
            elif qn <= 100:
                q['subject'] = 'Logical Reasoning'
                q['topic'] = 'Logical & Analytical Reasoning'
            else:
                q['subject'] = 'English'
                q['topic'] = 'English Language'

        mock_tests.append({
            'test_num': test_num,
            'questions': questions,
            'total_questions': len(questions),
        })

    return mock_tests


def parse_mock_questions(text, test_num):
    """Parse questions from mock test text."""
    questions = []

    # Remove mock test header
    text = re.sub(r'MOCK TEST\s*\d+\s*_{0,}', '', text, flags=re.IGNORECASE)

    # Split by Q number patterns
    parts = re.split(r'Q(\d+)\s*[.\s]', text)

    for i in range(1, len(parts) - 1, 2):
        q_num = int(parts[i])
        q_body = parts[i + 1].strip()

        q = extract_question_and_options(q_body)
        if q:
            q['question_num'] = q_num
            q['source'] = f'Mock Test {test_num}'
            questions.append(q)

    return questions


def parse_mock_answer_key(text):
    """Parse grid-style answer key for mock tests."""
    answer_map = {}
    lines = text.strip().split('\n')

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        # Look for number rows
        nums = re.findall(r'\d+', line)
        if nums and len(nums) >= 5:
            # Check if these look like question numbers
            try:
                first_num = int(nums[0])
                if 1 <= first_num <= 150:
                    # Next line should have answers
                    if i + 1 < len(lines):
                        next_line = lines[i + 1].strip()
                        answers = re.findall(r'[A-Da-d]', next_line)
                        for j, ans in enumerate(answers):
                            if j < len(nums):
                                answer_map[int(nums[j])] = ans.upper()
                        i += 2
                        continue
            except ValueError:
                pass
        i += 1

    return answer_map


def parse_mock_solutions(text):
    """Parse solutions for mock tests."""
    solution_map = {}

    # Solutions format: "1-.D :" or "1-D:" or "Q1. Answer: (D)"
    # Split by patterns like "1-" or "1." followed by answer
    parts = re.split(r'(\d+)\s*[-.:]\s*\.?\s*([A-Da-d])\s*[:.]\s*', text)

    for i in range(1, len(parts) - 2, 3):
        try:
            q_num = int(parts[i])
            explanation = parts[i + 2].strip()
            # Trim to reasonable length
            explanation = explanation[:1000]
            # Clean up
            explanation = re.sub(r'_{2,}', '', explanation).strip()
            if explanation:
                solution_map[q_num] = explanation
        except (ValueError, IndexError):
            continue

    return solution_map


# ---------------------------------------------------------------------------
# SAMPLE PAPER PDF PARSER
# ---------------------------------------------------------------------------

def parse_numbered_mcq_block(text):
    """Parse questions that use plain number format: '1. question', '2. question'."""
    questions = []
    seen_nums = set()
    last_passage = ''

    # Split by numbered question pattern (number followed by period at line start)
    parts = re.split(r'(?:^|\n)(\d+)\.\s+', text)

    for i in range(1, len(parts) - 1, 2):
        try:
            q_num = int(parts[i])
        except ValueError:
            continue

        if q_num in seen_nums:
            continue

        q_body = parts[i + 1].strip()

        # Check if this part is actually a passage (long text without options)
        q = extract_question_and_options(q_body)
        if q:
            q['question_num'] = q_num

            # Carry passage forward
            if q['passage'] and len(q['passage']) > 100:
                last_passage = q['passage']
            elif not q['passage'] and last_passage:
                q_lower = q['question_text'].lower()
                if any(kw in q_lower for kw in ['passage', 'paragraph', 'above', 'given text', 'the text']):
                    q['passage'] = last_passage

            questions.append(q)
            seen_nums.add(q_num)
        else:
            # No options found — this might be a passage block
            # Store it for subsequent questions
            if len(q_body) > 150:
                last_passage = q_body

    return questions


def parse_sample_paper_pdf(pdf_path):
    """Parse the 3-Year LLB Sample Paper."""
    questions = []

    # Questions: pages 2-22 (the paper starts on page 2-3)
    q_text = extract_text_from_pages(pdf_path, 2, 22)
    q_text = clean_text(q_text)

    # Answer key: pages 22-23
    ak_text = extract_text_from_pages(pdf_path, 22, 23)

    # Solutions: pages 23-43
    sol_text = extract_text_from_pages(pdf_path, 23, 43)
    sol_text = clean_text(sol_text)

    # Parse answer key
    answer_map = parse_mock_answer_key(ak_text)

    # Parse solutions
    solution_map = parse_sample_solutions(sol_text)

    # Try Q-prefix first, then plain numbers
    parsed = parse_mcq_block(q_text)
    if len(parsed) < 10:
        parsed = parse_numbered_mcq_block(q_text)

    for q in parsed:
        qn = q.get('question_num', 0)

        if qn in answer_map:
            q['correct_answer'] = answer_map[qn]
        if qn in solution_map:
            q['explanation'] = solution_map[qn]

        # Assign subjects based on 3-year LLB pattern
        if qn <= 24:
            q['subject'] = 'Legal Reasoning'
            q['topic'] = 'Legal Aptitude'
        elif qn <= 56:
            q['subject'] = 'General Knowledge'
            q['topic'] = 'GK & Current Affairs'
        elif qn <= 80:
            q['subject'] = 'Logical Reasoning'
            q['topic'] = 'Logical & Analytical Reasoning'
        else:
            q['subject'] = 'English'
            q['topic'] = 'English Language'

        q['source'] = 'Sample Paper (3-Year LLB)'
        questions.append(q)

    return questions


def parse_sample_solutions(text):
    """Parse solutions from sample paper."""
    solution_map = {}

    # Pattern: "1. Answer: (A)" followed by explanation
    parts = re.split(r'(\d+)\.\s*Answer:\s*\(([A-D])\)', text)

    for i in range(1, len(parts) - 2, 3):
        try:
            q_num = int(parts[i])
            explanation = parts[i + 2].strip()
            explanation = re.sub(r'_{2,}', '', explanation).strip()
            # Get just the explanation part before the next question
            explanation = explanation[:800]
            solution_map[q_num] = explanation
        except (ValueError, IndexError):
            continue

    # Also try "Answer: (A)\nExplanation:" pattern
    parts2 = re.split(r'(\d+)\s*[.]\s*', text)
    for i in range(1, len(parts2) - 1, 2):
        try:
            q_num = int(parts2[i])
            block = parts2[i + 1]
            ans_match = re.search(r'Answer:\s*\(([A-D])\)', block)
            if ans_match and q_num not in solution_map:
                expl_start = ans_match.end()
                explanation = block[expl_start:expl_start + 800].strip()
                if 'Explanation:' in explanation:
                    explanation = explanation.split('Explanation:', 1)[1].strip()
                solution_map[q_num] = explanation
        except (ValueError, IndexError):
            continue

    return solution_map


# ---------------------------------------------------------------------------
# TEACHING CONTENT EXTRACTOR
# ---------------------------------------------------------------------------

def extract_teaching_lessons(pdf_path):
    """Extract unique legal principles/passages as structured lessons."""
    import hashlib
    lessons = []
    seen = set()

    with pdfplumber.open(pdf_path) as pdf:
        total_pages = len(pdf.pages)

    for topic_name, start_page, end_page in LEGAL_TOPICS:
        end_page = min(end_page, total_pages)
        text = extract_text_from_pages(pdf_path, start_page, end_page)
        text = clean_text(text)

        # Split by question markers to isolate passages
        parts = re.split(r'Q\d+\s*[.\s]', text)

        topic_lessons = []
        for part in parts:
            part = part.strip()
            if len(part) < 150:
                continue

            # Extract the passage/principle portion (before options)
            # Remove options
            part_clean = re.split(r'(?:^|\n)\s*[A-D]\)', part)[0].strip()
            part_clean = re.split(r'(?:^|\n)\s*\([a-dA-D]\)', part_clean)[0].strip()
            part_clean = re.split(r'(?:^|\n)\s*[A-D]\]', part_clean)[0].strip()

            if len(part_clean) < 150:
                continue

            # Remove "Read the passage carefully and answer the question" headers
            part_clean = re.sub(
                r'^Read the (?:passage|following).*?(?:answer the question|question that follow)s?\s*',
                '', part_clean, flags=re.IGNORECASE
            ).strip()

            if len(part_clean) < 100:
                continue

            # Deduplicate using hash of first 120 chars
            key = hashlib.md5(part_clean[:120].lower().encode()).hexdigest()
            if key in seen:
                continue
            seen.add(key)

            # Auto-generate a title from the content
            title = _generate_lesson_title(part_clean, topic_name)

            topic_lessons.append({
                'topic': topic_name,
                'title': title,
                'content': part_clean,
                'subject': 'Legal Reasoning',
            })

        lessons.extend(topic_lessons)

    return lessons


def _generate_lesson_title(content, topic_name):
    """Generate a descriptive title from lesson content."""
    content_lower = content.lower()

    # Try to find key legal concepts mentioned
    concept_patterns = [
        (r'section\s+(\d+[A-Za-z]?)\s+of\s+(?:the\s+)?(.+?)(?:\s*,|\s*\.)', 'Section {} of {}'),
        (r'(?:principle|doctrine|rule|maxim)\s+of\s+([^.,:]+)', '{} Principle'),
        (r'(?:according to|under)\s+(?:the\s+)?(.+?act[^,.:]*)', 'Under {}'),
        (r'(strict liability|absolute liability|negligence|vicarious liability|nuisance|defamation|trespass)', '{}'),
        (r'(consideration|offer and acceptance|free consent|undue influence|fraud|misrepresentation|coercion)', '{}'),
        (r'(murder|culpable homicide|theft|robbery|dacoity|kidnapping|abetment)', '{}'),
        (r'(divorce|maintenance|adoption|guardianship|succession|marriage)', '{}'),
        (r'(arbitration|mediation|conciliation|adjudication)', '{}'),
        (r'(intellectual property|patent|trademark|copyright)', '{}'),
        (r'(cyber\s*crime|data protection|information technology)', '{}'),
        (r'(pollution|environment|wildlife|forest)', '{}'),
        (r'(consumer|unfair trade|product liability|service deficiency)', '{}'),
    ]

    for pattern, fmt in concept_patterns:
        m = re.search(pattern, content_lower)
        if m:
            groups = m.groups()
            if len(groups) == 2:
                return fmt.format(groups[0].strip().title(), groups[1].strip().title())
            elif len(groups) == 1:
                return groups[0].strip().title()

    # Fallback: use first sentence
    first_sent = re.split(r'[.!?]', content)[0].strip()
    if len(first_sent) > 80:
        first_sent = first_sent[:77] + '...'
    return first_sent or topic_name


# ---------------------------------------------------------------------------
# PREVIOUS YEAR PAPERS PARSER (set2)
# ---------------------------------------------------------------------------

def parse_previous_year_papers(set2_dir):
    """Parse memory-based previous year question papers from set2."""
    questions = []

    if not os.path.isdir(set2_dir):
        return questions

    pyp_files = [
        ('MH CET 3-year LLB 2024 Question Paper and Answers - Day 1', '2024 Day 1'),
        ('MH CET 3-Year LLB 2024 Question Paper and Answers (Day 2', '2024 Day 2'),
        ('MH CET 3-year LLB 2023 Memory-Based Questions with Answer - Day 1', '2023 Day 1'),
        ('MH CET 3-year LLB 2023 Memory-Based Questions with Answer - Day 2', '2023 Day 2'),
    ]

    for keyword, label in pyp_files:
        pdf_path = None
        for f in os.listdir(set2_dir):
            if f.endswith('.pdf') and keyword.lower() in f.lower():
                pdf_path = os.path.join(set2_dir, f)
                break

        if not pdf_path:
            continue

        print(f"  Parsing PYP: {label}...")
        with pdfplumber.open(pdf_path) as pdf:
            full_text = ''
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    full_text += t + '\n'

        full_text = clean_text(full_text)
        parsed = _parse_pyp_qa_format(full_text, label)
        questions.extend(parsed)

    return questions


def _parse_pyp_qa_format(text, source_label):
    """Parse previous year papers in 'Q. question\\nAns - answer' format."""
    questions = []

    # Split by numbered questions
    parts = re.split(r'(?:^|\n)(\d+)\s*[.)]\s*', text)

    for i in range(1, len(parts) - 1, 2):
        try:
            q_num = int(parts[i])
        except ValueError:
            continue

        block = parts[i + 1].strip()
        if not block or len(block) < 10:
            continue

        # Split question from answer
        ans_match = re.search(r'\n\s*(?:Ans|Answer)\s*[-:.]?\s*(.+?)(?:\n|$)', block, re.IGNORECASE)

        if ans_match:
            question_text = block[:ans_match.start()].strip()
            answer_text = ans_match.group(1).strip()
        else:
            question_text = block.strip()
            answer_text = ''

        if not question_text or len(question_text) < 5:
            continue

        # Categorize by content
        subject, topic = _categorize_pyp_question(question_text)

        questions.append({
            'question_text': question_text,
            'answer_text': answer_text,
            'correct_answer': '',  # No MCQ options
            'option_a': '', 'option_b': '', 'option_c': '', 'option_d': '',
            'passage': '',
            'explanation': f'Answer: {answer_text}' if answer_text else '',
            'subject': subject,
            'topic': topic,
            'source': f'PYP {source_label}',
            'is_pyp': True,
        })

    return questions


def _categorize_pyp_question(text):
    """Auto-categorize a previous year question by subject."""
    text_lower = text.lower()

    legal_keywords = ['section', 'article', 'act', 'court', 'judge', 'constitution',
                      'law', 'legal', 'ipc', 'penal', 'contract', 'tort', 'advocate',
                      'prosecution', 'conviction', 'bail', 'writ', 'habeas']
    english_keywords = ['antonym', 'synonym', 'spelling', 'meaning of', 'grammar',
                        'idiom', 'voice', 'tense', 'article', 'preposition', 'fill in']
    science_keywords = ['vitamin', 'gas', 'chemical', 'element', 'disease', 'blood',
                        'planet', 'newton', 'physics', 'biology', 'cell', 'acid',
                        'device', 'rays', 'calories', 'co2', 'oxygen']

    if any(k in text_lower for k in legal_keywords):
        return 'Legal Reasoning', 'Legal Aptitude (PYP)'
    elif any(k in text_lower for k in english_keywords):
        return 'English', 'English Language (PYP)'
    elif any(k in text_lower for k in science_keywords):
        return 'General Knowledge', 'Science & Technology (PYP)'
    else:
        return 'General Knowledge', 'GK & Current Affairs (PYP)'


# ---------------------------------------------------------------------------
# SYLLABUS / STUDY GUIDE CONTENT
# ---------------------------------------------------------------------------

def get_syllabus_content():
    """Return structured syllabus content for teaching modules."""
    return {
        'Legal Reasoning': {
            'description': 'Legal aptitude, contract law, torts, criminal law, constitutional law and more',
            'topics': [
                {
                    'name': 'Contract Law',
                    'key_concepts': [
                        'Definition and essentials of a valid contract (Section 10)',
                        'Offer and Acceptance (Sections 2-9)',
                        'Consideration (Sections 23-25)',
                        'Free Consent: Coercion, Undue Influence, Fraud, Misrepresentation (Sections 13-22)',
                        'Capacity to Contract: Minors, Persons of unsound mind (Sections 11-12)',
                        'Void and Voidable agreements (Sections 24-30)',
                        'Performance of Contracts (Sections 37-67)',
                        'Breach of Contract and Remedies (Sections 73-75)',
                        'Indemnity and Guarantee (Sections 124-147)',
                        'Bailment and Pledge (Sections 148-181)',
                        'Agency (Sections 182-238)',
                    ]
                },
                {
                    'name': 'Law of Torts',
                    'key_concepts': [
                        'Definition and Nature of Tort',
                        'General Defences in Tort Law',
                        'Negligence: Duty of Care, Breach, Causation, Remoteness of Damage',
                        'Strict Liability (Rylands v Fletcher, 1868)',
                        'Absolute Liability (M.C. Mehta v Union of India)',
                        'Nuisance: Public and Private',
                        'Defamation: Libel and Slander',
                        'Trespass to Person: Assault, Battery, False Imprisonment',
                        'Vicarious Liability: Employer-Employee, Principal-Agent',
                        'Consumer Protection and Product Liability',
                        'Remedies in Tort: Damages, Injunction',
                    ]
                },
                {
                    'name': 'Criminal Law',
                    'key_concepts': [
                        'General Principles: Actus Reus and Mens Rea',
                        'IPC: Offences against the State (Sections 121-130)',
                        'Offences against Public Tranquility (Sections 141-160)',
                        'Murder vs Culpable Homicide (Sections 299-304)',
                        'Hurt and Grievous Hurt (Sections 319-338)',
                        'Theft, Extortion, Robbery, Dacoity (Sections 378-402)',
                        'Criminal Breach of Trust (Sections 405-409)',
                        'Cheating and Fraud (Sections 415-420)',
                        'Defamation under Criminal Law (Sections 499-502)',
                        'Right of Private Defence (Sections 96-106)',
                        'Abetment (Sections 107-120)',
                    ]
                },
                {
                    'name': 'Constitutional Law',
                    'key_concepts': [
                        'Fundamental Rights (Articles 12-35)',
                        'Right to Equality (Articles 14-18)',
                        'Right to Freedom (Article 19)',
                        'Right against Exploitation (Articles 23-24)',
                        'Right to Freedom of Religion (Articles 25-28)',
                        'Right to Constitutional Remedies - Writs (Article 32)',
                        'Directive Principles of State Policy (Articles 36-51)',
                        'Fundamental Duties (Article 51A)',
                        'Amendment of Constitution (Article 368)',
                        'Emergency Provisions (Articles 352-360)',
                    ]
                },
            ]
        },
        'General Knowledge': {
            'description': 'Current affairs, Indian polity, history, geography, science',
            'topics': [
                {'name': 'Indian Polity & Governance', 'key_concepts': [
                    'President, Vice President, Prime Minister', 'Parliament: Lok Sabha & Rajya Sabha',
                    'Supreme Court and High Courts', 'Election Commission', 'NITI Aayog',
                    'Constitutional Bodies', 'Panchayati Raj', 'Important Constitutional Amendments'
                ]},
                {'name': 'Indian History', 'key_concepts': [
                    'Ancient India: Maurya, Gupta dynasties', 'Medieval India: Delhi Sultanate, Mughal Empire',
                    'Modern India: British Rule, Freedom Movement', 'Important dates and events',
                    'Quit India Movement (1942)', 'Champaran Satyagraha', 'Partition and Independence'
                ]},
                {'name': 'Geography', 'key_concepts': [
                    'Indian states and capitals', 'Rivers, mountains, national parks',
                    'World geography: continents, countries, capitals', 'UNESCO World Heritage Sites in India'
                ]},
                {'name': 'Science & Technology', 'key_concepts': [
                    'ISRO missions: Chandrayaan, Mangalyaan', 'Important scientific discoveries',
                    'Human body: vitamins, diseases', 'Basic physics and chemistry concepts',
                    'Nobel Prize winners', 'Digital India initiatives'
                ]},
                {'name': 'Current Affairs', 'key_concepts': [
                    'Awards: Bharat Ratna, Padma awards, Nobel Prize', 'Sports: Olympics, Commonwealth, Cricket',
                    'International organisations: UN, WHO, WTO, IMF', 'Recent government policies and schemes',
                    'Important days and themes', 'Books and authors'
                ]},
            ]
        },
        'Logical Reasoning': {
            'description': 'Analytical reasoning, critical thinking, puzzles, verbal and non-verbal reasoning',
            'topics': [
                {'name': 'Verbal Reasoning', 'key_concepts': [
                    'Statement and Assumption', 'Statement and Inference', 'Statement and Conclusion',
                    'Statement-Course of Action', 'Statement and Argument', 'Assertion and Reason',
                    'Cause and Effect', 'Fact-Inference-Judgement'
                ]},
                {'name': 'Analytical Reasoning', 'key_concepts': [
                    'Syllogism', 'Blood Relations', 'Coding-Decoding', 'Direction and Distance',
                    'Ranking and Order', 'Analogy', 'Classification', 'Series (Verbal and Non-Verbal)'
                ]},
                {'name': 'Puzzles & Arrangements', 'key_concepts': [
                    'Seating Arrangement (Linear and Circular)', 'Scheduling Problems',
                    'Logical Puzzles', 'Data Sufficiency'
                ]},
            ]
        },
        'English': {
            'description': 'Reading comprehension, grammar, vocabulary, verbal ability',
            'topics': [
                {'name': 'Vocabulary', 'key_concepts': [
                    'Synonyms and Antonyms', 'One-word substitutions', 'Idioms and Phrases',
                    'Foreign words and legal terminology', 'Homonyms and Homophones'
                ]},
                {'name': 'Grammar', 'key_concepts': [
                    'Tenses', 'Active and Passive Voice', 'Direct and Indirect Speech',
                    'Subject-Verb Agreement', 'Articles, Prepositions, Conjunctions',
                    'Sentence Correction', 'Error Spotting'
                ]},
                {'name': 'Comprehension', 'key_concepts': [
                    'Reading Comprehension Passages', 'Para Jumbles', 'Sentence Completion',
                    'Cloze Test', 'Critical Reasoning in passages'
                ]},
            ]
        },
        'Mathematics': {
            'description': 'Algebra, arithmetic, geometry, data interpretation (5-year LLB only)',
            'topics': [
                {'name': 'Arithmetic', 'key_concepts': [
                    'Percentage, Profit & Loss', 'Ratio and Proportion', 'Time, Speed & Distance',
                    'Time and Work', 'Simple & Compound Interest', 'Averages', 'Mixtures & Alligations'
                ]},
                {'name': 'Algebra & Geometry', 'key_concepts': [
                    'Linear equations', 'Quadratic equations', 'Mensuration: Area, Volume, Surface Area',
                    'Triangles, Circles, Quadrilaterals', 'Coordinate Geometry basics'
                ]},
                {'name': 'Data Interpretation', 'key_concepts': [
                    'Tables', 'Bar Graphs', 'Pie Charts', 'Line Graphs', 'Venn Diagrams'
                ]},
            ]
        },
    }


# ---------------------------------------------------------------------------
# MAIN PARSE ALL
# ---------------------------------------------------------------------------

def find_pdf(directory, keyword):
    """Find a PDF file containing the keyword in its name."""
    for f in os.listdir(directory):
        if f.endswith('.pdf') and keyword.lower() in f.lower():
            return os.path.join(directory, f)
    return None


def parse_all_pdfs(pdf_directory):
    """Parse all available PDFs and return structured data."""
    results = {
        'maths': [],
        'legal_reasoning': [],
        'mock_tests': [],
        'sample_paper': [],
        'lessons': [],
        'previous_year': [],
        'syllabus': get_syllabus_content(),
    }

    # Maths PDF
    maths_pdf = find_pdf(pdf_directory, 'Maths Practice')
    if maths_pdf:
        print("Parsing Maths Practice Questions...")
        results['maths'] = parse_maths_pdf(maths_pdf)
        print(f"  Found {len(results['maths'])} maths questions")

    # Legal Reasoning PDF
    legal_pdf = find_pdf(pdf_directory, 'Legal Reasoning Practice')
    if legal_pdf:
        print("Parsing Legal Reasoning Practice Questions...")
        results['legal_reasoning'] = parse_legal_reasoning_pdf(legal_pdf)
        print(f"  Found {len(results['legal_reasoning'])} legal reasoning questions")

        # Extract teaching lessons from passages
        print("Extracting teaching lessons from Legal Reasoning PDF...")
        results['lessons'] = extract_teaching_lessons(legal_pdf)
        print(f"  Found {len(results['lessons'])} unique teaching lessons")

    # Mock Tests PDF
    mock_pdf = find_pdf(pdf_directory, '10 Free Mock Tests')
    if mock_pdf:
        print("Parsing 10 Mock Tests...")
        results['mock_tests'] = parse_mock_tests_pdf(mock_pdf)
        total_mock_q = sum(len(t['questions']) for t in results['mock_tests'])
        print(f"  Found {total_mock_q} mock test questions across {len(results['mock_tests'])} tests")

    # Sample Paper PDF
    sample_pdf = find_pdf(pdf_directory, 'Sample Papers')
    if sample_pdf:
        print("Parsing Sample Paper...")
        results['sample_paper'] = parse_sample_paper_pdf(sample_pdf)
        print(f"  Found {len(results['sample_paper'])} sample paper questions")

    # Previous Year Papers (set2)
    set2_dir = os.path.join(pdf_directory, 'set2')
    if os.path.isdir(set2_dir):
        print("Parsing Previous Year Papers (set2)...")
        results['previous_year'] = parse_previous_year_papers(set2_dir)
        print(f"  Found {len(results['previous_year'])} previous year questions")

    return results


if __name__ == '__main__':
    import sys
    pdf_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__)) + '/..'
    results = parse_all_pdfs(pdf_dir)

    total = (
        len(results['maths']) +
        len(results['legal_reasoning']) +
        sum(len(t['questions']) for t in results['mock_tests']) +
        len(results['sample_paper'])
    )
    print(f"\nTotal questions parsed: {total}")
