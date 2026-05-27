/**
 * LawPrep TTS — ElevenLabs + Browser Speech fallback
 *
 * Voices:  Rachel / Adam / Bella / Antoni (ElevenLabs)
 *          Browser Voice (free, Web Speech API fallback)
 * Keyboard: Space=play/pause  R=repeat  [=prev  ]=next  S=stop  E=explain
 * Mic:      E key or mic button → voice commands
 */
;(function () {
    'use strict';

    // ─── ElevenLabs voice catalogue ──────────────────────────────────────────
    const EL_VOICES = {
        '21m00Tcm4TlvDq8ikWAM': 'Rachel',
        'pNInz6obpgDQGcFmaJgB': 'Adam',
        'EXAVITQu4vr4xnSDxMaL': 'Bella',
        'ErXwobaYiN019PkySvjV': 'Antoni',
        '__browser__':           'Browser',
    };
    const FREE_TIER      = 10000;
    const WARN_THRESHOLD = 9000;
    const LS_VOICE_KEY   = 'lawprep_tts_voice';

    // ─── State ───────────────────────────────────────────────────────────────
    const synth      = window.speechSynthesis;
    let paragraphs   = [];   // [{text, el, wrapper, idx, isTitle}]
    let currentIdx   = -1;
    let isPlaying    = false;
    let rate         = 1.0;
    let voiceId      = localStorage.getItem(LS_VOICE_KEY) || '21m00Tcm4TlvDq8ikWAM';
    let currentAudio = null;   // HTMLAudioElement for EL playback
    let podcastActive = false;
    let micRec       = null;
    let isListening  = false;
    let dom          = {};

    // ─── Text cleaner (mirrors server-side _clean_text_for_tts) ─────────────
    function clean(text) {
        return (text || '')
            .replace(/\*{1,3}([^*]*)\*{1,3}/g, '$1')
            .replace(/_{1,3}([^_]*)_{1,3}/g, '$1')
            .replace(/#{1,6}\s+/g, '')
            .replace(/`[^`]*`/g, '')
            .replace(/\[([^\]]*)\]\([^)]+\)/g, '$1')
            .replace(/[•→►]/g, '')
            .replace(/_/g, ' ')
            .replace(/:\s*$/, '.')
            .replace(/\s+/g, ' ')
            .trim();
    }

    // ─── Init ─────────────────────────────────────────────────────────────────
    function init() {
        dom = {
            bar:        document.getElementById('ttsBar'),
            playBtn:    document.getElementById('ttsPlay'),
            stopBtn:    document.getElementById('ttsStop'),
            repeatBtn:  document.getElementById('ttsRepeat'),
            prevBtn:    document.getElementById('ttsPrev'),
            nextBtn:    document.getElementById('ttsNext'),
            progress:   document.getElementById('ttsProgress'),
            status:     document.getElementById('ttsStatus'),
            speedSel:   document.getElementById('ttsSpeed'),
            voiceSel:   document.getElementById('ttsVoice'),
            podBtn:     document.getElementById('ttsPodcastBar'),
            micBtn:     document.getElementById('ttsMic'),
            charsLeft:  document.getElementById('ttsCharsLeft'),
        };

        if (!dom.bar || !document.getElementById('lessonTtsContent')) return;

        buildParagraphList();
        restoreVoice();
        bindBar();
        bindKeyboard();
        initMic();
        showBar();
        fetchCharsUsed();
    }

    // ─── Paragraph collection ─────────────────────────────────────────────────
    function buildParagraphList() {
        paragraphs = [];

        const titleEl = document.getElementById('lessonTtsTitle');
        if (titleEl) {
            const t = clean(titleEl.textContent);
            if (t) paragraphs.push({ text: t, el: titleEl, wrapper: null, idx: 0, isTitle: true });
        }

        const container = document.getElementById('lessonTtsContent');
        if (container) {
            container.querySelectorAll('[data-tts-text]').forEach(wrapper => {
                const t = clean(wrapper.dataset.ttsText || wrapper.textContent);
                if (t.length < 6) return;
                const el = wrapper.querySelector('.lesson-para, .concept-item') || wrapper;
                const idx = paragraphs.length;
                paragraphs.push({ text: t, el, wrapper, idx, isTitle: false });
                wrapper.dataset.ttsBuiltIdx = String(idx);
            });
        }

        updateProgress();
    }

    // ─── Voice restore (localStorage) ────────────────────────────────────────
    function restoreVoice() {
        if (!dom.voiceSel) return;
        if (EL_VOICES[voiceId]) {
            dom.voiceSel.value = voiceId;
        }
        dom.voiceSel.addEventListener('change', () => {
            voiceId = dom.voiceSel.value;
            localStorage.setItem(LS_VOICE_KEY, voiceId);
        });
    }

    // ─── Character usage ──────────────────────────────────────────────────────
    function fetchCharsUsed() {
        fetch('/api/tts-usage')
            .then(r => r.json())
            .then(d => updateCharsDisplay(d.chars_remaining, d.chars_used))
            .catch(() => {});
    }

    function updateCharsDisplay(remaining, used) {
        if (!dom.charsLeft) return;
        if (used === undefined || used === null) return;

        if (used >= FREE_TIER) {
            dom.charsLeft.textContent = '⚠ EL quota hit';
            dom.charsLeft.style.color = '#ef4444';
            // Auto-switch to browser if quota exhausted
            if (dom.voiceSel && dom.voiceSel.value !== '__browser__') {
                dom.voiceSel.value = '__browser__';
                voiceId = '__browser__';
                localStorage.setItem(LS_VOICE_KEY, '__browser__');
                setStatus('⚠ ElevenLabs quota hit — switched to Browser voice');
            }
        } else if (used >= WARN_THRESHOLD) {
            dom.charsLeft.textContent = `⚠ ~${remaining.toLocaleString()} chars left`;
            dom.charsLeft.style.color = '#f59e0b';
        } else {
            dom.charsLeft.textContent = `~${remaining.toLocaleString()} chars left`;
            dom.charsLeft.style.color = '#64748b';
        }
    }

    // ─── Core speak: ElevenLabs ───────────────────────────────────────────────
    async function speakTextEL(text, onDone) {
        // Stop any existing audio
        if (currentAudio) {
            currentAudio.onended = null;
            currentAudio.pause();
            currentAudio = null;
        }

        let resp;
        try {
            resp = await fetch('/api/tts', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text, voice_id: voiceId }),
            });
        } catch (err) {
            console.warn('EL fetch error:', err);
            speakTextBrowser(text, onDone);
            return;
        }

        if (resp.status === 429) {
            // Quota exceeded — fall back silently
            const d = await resp.json().catch(() => ({}));
            updateCharsDisplay(0, d.chars_used || FREE_TIER);
            speakTextBrowser(text, onDone);
            return;
        }

        if (!resp.ok) {
            console.warn('EL error', resp.status);
            speakTextBrowser(text, onDone);
            return;
        }

        const blob = await resp.blob();
        const url  = URL.createObjectURL(blob);
        const audio = new Audio(url);
        audio.playbackRate = Math.min(rate, 2.0);   // speed via playbackRate
        currentAudio = audio;

        audio.onended = () => {
            URL.revokeObjectURL(url);
            currentAudio = null;
            fetchCharsUsed();
            if (onDone) onDone();
        };
        audio.onerror = () => {
            URL.revokeObjectURL(url);
            currentAudio = null;
            speakTextBrowser(text, onDone);
        };

        audio.play().catch(() => speakTextBrowser(text, onDone));
    }

    // ─── Core speak: Browser SpeechSynthesis (fallback) ──────────────────────
    function speakTextBrowser(text, onDone) {
        if (!synth) { if (onDone) onDone(); return; }
        synth.cancel();

        // Pick best available browser voice
        const voices  = synth.getVoices();
        const indian  = voices.find(v => v.lang === 'en-IN');
        const british = voices.find(v => v.lang === 'en-GB');
        const english = voices.find(v => v.lang.startsWith('en'));
        const bVoice  = indian || british || english || null;

        const utt = new SpeechSynthesisUtterance(text);
        utt.rate   = rate;
        utt.pitch  = 1.0;
        utt.volume = 1.0;
        if (bVoice) utt.voice = bVoice;
        utt.onend  = onDone || null;
        utt.onerror = e => {
            if (e.error !== 'interrupted' && e.error !== 'canceled')
                console.warn('Browser TTS:', e.error);
        };
        synth.speak(utt);

        // Chrome bug: long utterances silently pause
        const guard = setInterval(() => {
            if (!synth.speaking) { clearInterval(guard); return; }
            if (synth.paused) synth.resume();
        }, 8000);
    }

    // ─── Dispatcher ───────────────────────────────────────────────────────────
    function speakText(text, onDone) {
        if (voiceId === '__browser__') {
            speakTextBrowser(text, onDone);
        } else {
            speakTextEL(text, onDone);
        }
    }

    // ─── Paragraph chain ──────────────────────────────────────────────────────
    function speakIdx(idx) {
        if (!isPlaying) return;
        if (idx < 0 || idx >= paragraphs.length) {
            setStatus('✓ Finished reading');
            isPlaying = false;
            setPlayIcon('▶');
            clearHighlight();
            return;
        }

        currentIdx = idx;
        highlight(idx);
        scrollTo(idx);
        updateProgress();

        const para  = paragraphs[idx];
        const text  = para.isTitle ? para.text + '.' : para.text;
        const delay = para.isTitle ? 500 : 50;

        speakText(text, () => {
            if (!isPlaying) return;
            setTimeout(() => speakIdx(idx + 1), delay);
        });
    }

    // ─── Playback controls ────────────────────────────────────────────────────
    function play() {
        if (isPlaying) return;
        isPlaying = true;
        setPlayIcon('⏸');
        setStatus('▶ Reading…');
        document.body.classList.add('tts-active');
        speakIdx(currentIdx >= 0 ? currentIdx : 0);
    }

    function pause() {
        if (!isPlaying) return;
        // Stop audio (both EL and browser)
        if (currentAudio) { currentAudio.pause(); currentAudio = null; }
        if (synth) synth.cancel();
        isPlaying = false;
        setPlayIcon('▶');
        setStatus('⏸ Paused — Space to resume');
    }

    function stop() {
        if (currentAudio) { currentAudio.pause(); currentAudio = null; }
        if (synth) synth.cancel();
        isPlaying     = false;
        podcastActive = false;
        currentIdx    = 0;
        clearHighlight();
        setPlayIcon('▶');
        setStatus('');
        updateProgress();
        if (dom.podBtn) dom.podBtn.classList.remove('active');
    }

    function togglePlay() {
        if (isPlaying) pause();
        else           play();
    }

    function repeatPara() {
        if (currentIdx < 0) { play(); return; }
        if (currentAudio) { currentAudio.pause(); currentAudio = null; }
        if (synth) synth.cancel();
        isPlaying = true;
        setPlayIcon('⏸');
        setStatus('↩ Repeating…');
        speakIdx(currentIdx);
    }

    function prevPara() {
        if (currentAudio) { currentAudio.pause(); currentAudio = null; }
        if (synth) synth.cancel();
        isPlaying = true;
        setPlayIcon('⏸');
        speakIdx(Math.max(0, currentIdx - 1));
    }

    function nextPara() {
        if (currentAudio) { currentAudio.pause(); currentAudio = null; }
        if (synth) synth.cancel();
        isPlaying = true;
        setPlayIcon('⏸');
        speakIdx(Math.min(paragraphs.length - 1, currentIdx + 1));
    }

    // ─── Podcast mode ─────────────────────────────────────────────────────────
    function startPodcast() {
        stop();
        podcastActive = true;
        if (dom.podBtn) dom.podBtn.classList.add('active');
        setStatus('🎙 Podcast mode');

        const list = paragraphs.map(p => ({ ...p }));
        list.push({
            text: 'That is all for this lesson. You are now ready to test yourself!',
            el: null, wrapper: null, idx: list.length, isTitle: false,
        });

        const orig = paragraphs;
        paragraphs = list;
        isPlaying  = true;
        setPlayIcon('⏸');
        currentIdx = 0;

        function speak(idx) {
            if (!isPlaying || idx >= list.length) {
                paragraphs = orig;
                podcastActive = false;
                if (dom.podBtn) dom.podBtn.classList.remove('active');
                stop();
                setStatus('🎙 Podcast finished!');
                return;
            }
            currentIdx = idx;
            updateProgress();
            if (list[idx].el) { highlight(idx); scrollTo(idx); }
            speakText(list[idx].text, () => {
                if (!isPlaying) { paragraphs = orig; return; }
                setTimeout(() => speak(idx + 1), list[idx].isTitle ? 500 : 50);
            });
        }
        speak(0);
    }

    // ─── Tutor Explain ────────────────────────────────────────────────────────
    window.ttsExplainBtn = function (btn) {
        const wrapper = btn.closest('[data-tts-built-idx]');
        const idx = wrapper ? parseInt(wrapper.dataset.ttsBuiltIdx || '-1') : currentIdx;
        triggerExplain(idx, false, '', 0);
    };

    async function triggerExplain(paraIdx, deeper, prevExp, depth) {
        const para = paragraphs[paraIdx];
        if (!para) return;
        if (depth >= 3) { setStatus('Max explanation depth — continuing lesson'); return; }

        // Stop reading
        if (currentAudio) { currentAudio.pause(); currentAudio = null; }
        if (synth) synth.cancel();
        isPlaying = false;
        setPlayIcon('▶');
        setStatus('🧑‍🏫 Asking your tutor…');

        // Remove any existing box for this para
        document.querySelector(`.tts-explain-box[data-para-idx="${paraIdx}"]`)?.remove();

        // Build explanation box
        const box = document.createElement('div');
        box.className = 'tts-explain-box';
        box.dataset.paraIdx = String(paraIdx);
        box.innerHTML = `
            <div class="explain-header">
                <span>🧑‍🏫</span> Your AI Tutor
                ${depth > 0 ? `<span style="opacity:.5;font-size:.65rem;margin-left:.5rem;">Level ${depth + 1}</span>` : ''}
            </div>
            <div class="tts-explain-loading">Thinking of the best way to explain…</div>
            <div class="tts-explain-text explain-text"></div>
            <div class="tts-explain-actions hidden explain-actions">
                <button class="btn-continue-lesson">▶ Continue Lesson</button>
                <button class="btn-explain-further btn-deeper">🔍 Explain Further</button>
            </div>`;

        const anchor = para.wrapper || para.el;
        if (anchor) anchor.insertAdjacentElement('afterend', box);
        else document.getElementById('lessonTtsContent').appendChild(box);
        box.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

        const loadingEl = box.querySelector('.tts-explain-loading');
        const textEl    = box.querySelector('.explain-text');
        const actionsEl = box.querySelector('.explain-actions');

        try {
            const resp = await fetch('/api/tutor-explain', {
                method:  'POST',
                headers: { 'Content-Type': 'application/json' },
                body:    JSON.stringify({
                    text:            para.text,
                    deeper:          !!deeper,
                    prev_explanation: prevExp || '',
                    depth,
                }),
            });

            if (!resp.ok) throw new Error('API error ' + resp.status);
            const data = await resp.json();
            if (!data.explanation) throw new Error('Empty response');

            loadingEl.style.display = 'none';
            textEl.textContent = data.explanation;
            actionsEl.classList.remove('hidden');

            // Wire action buttons
            actionsEl.querySelector('.btn-continue-lesson').addEventListener('click', () => {
                box.remove();
                if (currentAudio) { currentAudio.pause(); currentAudio = null; }
                if (synth) synth.cancel();
                isPlaying = true;
                setPlayIcon('⏸');
                setStatus('▶ Continuing…');
                speakIdx(paraIdx + 1);
            });
            actionsEl.querySelector('.btn-explain-further').addEventListener('click', () => {
                box.remove();
                triggerExplain(paraIdx, true, data.explanation, depth + 1);
            });

            // Read explanation aloud
            setStatus('🔊 Tutor explaining…');
            speakText(data.explanation, () => {
                setStatus('✓ Continue lesson or go deeper?');
            });

        } catch (err) {
            loadingEl.textContent = '⚠ Could not reach tutor. Check your connection.';
            console.error('Explain error:', err);
            setStatus('');
        }
    }

    function explainCurrent() {
        triggerExplain(currentIdx >= 0 ? currentIdx : 0, false, '', 0);
    }

    // ─── Highlight / Scroll ───────────────────────────────────────────────────
    function highlight(idx) {
        clearHighlight();
        const el = paragraphs[idx]?.el;
        if (el) el.classList.add('tts-reading');
    }

    function clearHighlight() {
        document.querySelectorAll('.tts-reading').forEach(el => el.classList.remove('tts-reading'));
    }

    function scrollTo(idx) {
        const el = paragraphs[idx]?.el;
        if (el) el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }

    // ─── UI Helpers ───────────────────────────────────────────────────────────
    function showBar() {
        dom.bar.classList.remove('hidden');
        document.body.classList.add('tts-active');
        if (dom.micBtn) dom.micBtn.classList.remove('hidden');
    }

    function setPlayIcon(icon) { if (dom.playBtn) dom.playBtn.textContent = icon; }

    function setStatus(text) { if (dom.status) dom.status.textContent = text; }

    function updateProgress() {
        if (!dom.progress) return;
        const total = paragraphs.length;
        const cur   = currentIdx >= 0 ? currentIdx + 1 : 0;
        dom.progress.textContent = total > 0 ? `Paragraph ${cur} of ${total}` : '';
    }

    // ─── Bar button bindings ──────────────────────────────────────────────────
    function bindBar() {
        dom.playBtn?.addEventListener('click', togglePlay);
        dom.stopBtn?.addEventListener('click', stop);
        dom.repeatBtn?.addEventListener('click', repeatPara);
        dom.prevBtn?.addEventListener('click', prevPara);
        dom.nextBtn?.addEventListener('click', nextPara);
        dom.podBtn?.addEventListener('click', startPodcast);

        dom.speedSel?.addEventListener('change', () => {
            rate = parseFloat(dom.speedSel.value);
            if (currentAudio) currentAudio.playbackRate = Math.min(rate, 2.0);
            // Browser speech: restart current para at new rate
            if (voiceId === '__browser__' && isPlaying) { speakIdx(currentIdx); }
        });
    }

    // ─── Keyboard shortcuts ───────────────────────────────────────────────────
    function bindKeyboard() {
        document.addEventListener('keydown', e => {
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA'
                || e.target.isContentEditable) return;
            if (!dom.bar || dom.bar.classList.contains('hidden')) return;
            switch (e.key) {
                case ' ':        e.preventDefault(); togglePlay();  break;
                case 'r': case 'R': repeatPara();                   break;
                case ']':        nextPara();                        break;
                case '[':        prevPara();                        break;
                case 's': case 'S': stop();                         break;
                case 'e': case 'E': explainCurrent();               break;
            }
        });
    }

    // ─── Floating mic ─────────────────────────────────────────────────────────
    function initMic() {
        const Rec = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!Rec || !dom.micBtn) return;

        micRec = new Rec();
        micRec.continuous     = false;
        micRec.lang           = 'en-IN';
        micRec.interimResults = false;
        micRec.maxAlternatives = 1;

        micRec.onresult = e => {
            const cmd = e.results[0][0].transcript.toLowerCase().trim();
            handleVoiceCmd(cmd);
        };
        micRec.onend = () => {
            isListening = false;
            dom.micBtn.classList.remove('listening');
        };
        micRec.onerror = () => {
            isListening = false;
            dom.micBtn.classList.remove('listening');
        };

        dom.micBtn.addEventListener('click', () => {
            if (isListening) { micRec.stop(); return; }
            isListening = true;
            dom.micBtn.classList.add('listening');
            setStatus('🎤 Listening…');
            try { micRec.start(); }
            catch (e) { isListening = false; dom.micBtn.classList.remove('listening'); }
        });
    }

    function handleVoiceCmd(cmd) {
        setStatus('🎤 "' + cmd + '"');
        if (/explain|tell me more|explain this/.test(cmd))        explainCurrent();
        else if (/repeat|again|say that again/.test(cmd))         repeatPara();
        else if (/next|continue|move on/.test(cmd))               nextPara();
        else if (/previous|go back|back|prev/.test(cmd))          prevPara();
        else if (/pause|wait|hold on/.test(cmd))                  pause();
        else if (/play|start|read|continue reading/.test(cmd))    play();
        else if (/stop/.test(cmd))                                 stop();
        else if (/podcast/.test(cmd))                             startPodcast();
        else setTimeout(() => setStatus(''), 2500);
    }

    // ─── Public API ───────────────────────────────────────────────────────────
    window.LawPrepTTS = {
        play, pause, stop, togglePlay, repeatPara, prevPara, nextPara,
        startPodcast, triggerExplain, explainCurrent,
    };

    // ─── Boot ─────────────────────────────────────────────────────────────────
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
