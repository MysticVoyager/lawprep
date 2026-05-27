// ==========================================
// MH-CET Law 2026 - LawPrep Portal
// Frontend JavaScript
// ==========================================

// Exam countdown (April 2026)
function updateExamCountdown() {
    const examDate = new Date('2026-04-01'); // MH-CET Law 2026 - Day 1
    const now = new Date();
    const diff = examDate - now;

    if (diff <= 0) return;

    const days = Math.floor(diff / (1000 * 60 * 60 * 24));
    const el = document.getElementById('examCountdown');
    if (el) {
        el.innerHTML = `<strong>${days}</strong> days to MH-CET Law`;
    }
}

updateExamCountdown();

// Bookmark toggle
function toggleBookmark(questionId, btn) {
    fetch('/api/bookmark', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question_id: questionId })
    })
    .then(r => r.json())
    .then(data => {
        if (data.bookmarked) {
            btn.classList.add('active');
        } else {
            btn.classList.remove('active');
        }
    });
}

// Smooth scroll for study cards
document.querySelectorAll('.study-options .option').forEach(opt => {
    opt.style.cursor = 'pointer';
});

// Keyboard navigation for quizzes
document.addEventListener('keydown', (e) => {
    // A, B, C, D keys for option selection
    const key = e.key.toUpperCase();
    if (['A', 'B', 'C', 'D'].includes(key)) {
        const activeQ = document.querySelector('.quiz-question:not(.hidden)');
        if (activeQ) {
            const opt = activeQ.querySelector(`[data-letter="${key}"]`);
            if (opt) opt.click();
        }

        // Mock test
        const activeMock = document.querySelector('.mock-question:not(.hidden)');
        if (activeMock) {
            const opt = activeMock.querySelector(`[data-letter="${key}"]`);
            if (opt) opt.click();
        }
    }

    // Enter to submit answer
    if (e.key === 'Enter') {
        const submitBtn = document.getElementById('submitBtn');
        if (submitBtn && !submitBtn.classList.contains('hidden') && !submitBtn.disabled) {
            submitBtn.click();
            return;
        }

        const nextBtn = document.getElementById('nextBtn');
        if (nextBtn && !nextBtn.classList.contains('hidden')) {
            nextBtn.click();
            return;
        }

        const finishBtn = document.getElementById('finishBtn');
        if (finishBtn && !finishBtn.classList.contains('hidden')) {
            finishBtn.click();
            return;
        }
    }

    // Arrow keys for navigation
    if (e.key === 'ArrowRight') {
        const nextBtn = document.getElementById('nextBtn');
        if (nextBtn && !nextBtn.classList.contains('hidden')) nextBtn.click();
    }
    if (e.key === 'ArrowLeft') {
        const prevBtn = document.getElementById('prevBtn');
        if (prevBtn && !prevBtn.disabled) prevBtn.click();
    }
});
