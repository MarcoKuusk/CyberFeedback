// Consent text version recorded with every submission.
// NOTE: the wording in index.html is a DRAFT pending ethics review. Bump this
// to '1.0' only once the approved text is in place, so stored records always
// say which version a respondent actually agreed to.
const CONSENT_VERSION = '1.0-draft';

const state = {
    currentPage: 'home',
    campaign: null,
    // The link token a respondent arrived with, and the single track it grants.
    linkToken: null,
    grantedTrack: null,
    reportType: null,
    respondentId: null,
    consentAgreed: false,
    questions: [],
    currentQuestionIndex: 0,
    answers: [],
    summary: null,
};

const reportLabels = {
    employee: 'Employee',
    organization: 'Organization',
};

const elements = {};

document.addEventListener('DOMContentLoaded', () => {
    cacheElements();
    bindEvents();
    showPage('home');
    resolveCampaign();
});

/**
 * Escape before any interpolation into innerHTML. Questionnaire text is trusted
 * configuration, but org_name arrives from campaign creation, so nothing
 * user-influenced may reach the DOM as raw markup.
 */
function escapeHtml(value) {
    return String(value === null || value === undefined ? '' : value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function cacheElements() {
    elements.pages = document.querySelectorAll('.page');
    elements.navLinks = document.querySelectorAll('[data-target]');
    elements.startButtons = document.querySelectorAll('[data-start]');
    elements.segments = document.querySelectorAll('.segment');
    elements.homeLink = document.getElementById('homeLink');
    elements.assessmentIntro = document.getElementById('assessmentIntro');
    elements.consentSection = document.getElementById('consentSection');
    elements.assessmentSection = document.getElementById('assessmentSection');
    elements.reviewSection = document.getElementById('reviewSection');
    elements.feedbackSection = document.getElementById('feedbackSection');
    elements.workspaceEyebrow = document.getElementById('workspaceEyebrow');
    elements.workspaceTitle = document.getElementById('workspaceTitle');
    elements.workspaceSubtitle = document.getElementById('workspaceSubtitle');
    elements.questionCategory = document.getElementById('questionCategory');
    elements.questionTitle = document.getElementById('questionTitle');
    elements.questionHelper = document.getElementById('questionHelper');
    elements.questionOptions = document.getElementById('questionOptions');
    elements.questionError = document.getElementById('questionError');
    elements.progressText = document.getElementById('progressText');
    elements.progressBar = document.getElementById('progressBar');
    elements.backButton = document.getElementById('backButton');
    elements.nextButton = document.getElementById('nextButton');
    elements.reviewList = document.getElementById('reviewList');
    elements.editResponsesButton = document.getElementById('editResponsesButton');
    elements.submitAssessmentButton = document.getElementById('submitAssessmentButton');
    elements.overallScore = document.getElementById('overallScore');
    elements.maturityLabel = document.getElementById('maturityLabel');
    elements.topFocus = document.getElementById('topFocus');
    elements.reportTypeLabel = document.getElementById('reportTypeLabel');
    elements.questionCountLabel = document.getElementById('questionCountLabel');
    elements.strengthList = document.getElementById('strengthList');
    elements.riskList = document.getElementById('riskList');
    elements.actionList = document.getElementById('actionList');
    elements.categoryScoreList = document.getElementById('categoryScoreList');
    elements.downloadButton = document.getElementById('downloadButton');
    elements.reportStatus = document.getElementById('reportStatus');

    // Campaign gate
    elements.campaignEyebrow = document.getElementById('campaignEyebrow');
    elements.campaignHeading = document.getElementById('campaignHeading');
    elements.campaignDetail = document.getElementById('campaignDetail');

    // Consent
    elements.consentCheckbox = document.getElementById('consentCheckbox');
    elements.consentError = document.getElementById('consentError');
    elements.consentContinueButton = document.getElementById('consentContinueButton');
    elements.consentBackButton = document.getElementById('consentBackButton');
    elements.consentVersionLabel = document.getElementById('consentVersionLabel');
}

function bindEvents() {
    elements.navLinks.forEach((link) => {
        link.addEventListener('click', (event) => {
            event.preventDefault();
            showPage(link.dataset.target);
        });
    });

    elements.homeLink.addEventListener('click', (event) => {
        event.preventDefault();
        showPage('home');
    });

    elements.startButtons.forEach((button) => {
        button.addEventListener('click', () => startAssessment(button.dataset.start));
    });

    elements.backButton.addEventListener('click', handleBack);
    elements.nextButton.addEventListener('click', handleNext);
    elements.editResponsesButton.addEventListener('click', () => {
        toggleSection('assessment');
        renderQuestion();
    });
    elements.submitAssessmentButton.addEventListener('click', submitAssessment);
    elements.downloadButton.addEventListener('click', generateAndDownloadReport);

    elements.consentContinueButton.addEventListener('click', acceptConsent);
    elements.consentBackButton.addEventListener('click', () => {
        toggleSection('intro');
        showPage('home');
    });
    elements.consentCheckbox.addEventListener('change', () => {
        if (elements.consentCheckbox.checked) {
            elements.consentError.classList.add('hidden');
        }
    });

    elements.consentVersionLabel.textContent = CONSENT_VERSION;
}

function showPage(pageId) {
    state.currentPage = pageId;
    elements.pages.forEach((page) => page.classList.toggle('page-active', page.id === pageId));
}

// ---------------------------------------------------------------------------
// Campaign context
// ---------------------------------------------------------------------------

function linkTokenFromUrl() {
    // Canonical form is /c/<token>; the query form is kept so an older link
    // still resolves rather than dead-ending on a blank page.
    const fromPath = window.location.pathname.match(/^\/c\/([0-9a-f]{32})\/?$/);
    if (fromPath) {
        return fromPath[1];
    }
    const value = new URLSearchParams(window.location.search).get('token');
    return value && /^[0-9a-f]{32}$/.test(value) ? value : null;
}

async function resolveCampaign() {
    const token = linkTokenFromUrl();

    if (!token) {
        elements.campaignEyebrow.textContent = 'No assessment link';
        elements.campaignHeading.textContent = 'An assessment link is required';
        elements.campaignDetail.textContent =
            'Open the link your organization sent you. It looks like .../c/ followed by a long code.';
        setTrackAvailability([]);
        return;
    }

    try {
        const response = await fetch(`/api/link/${token}`);
        const payload = await response.json();
        if (!response.ok) {
            throw new Error(payload.message || 'This assessment link could not be opened.');
        }

        // The server derives the track from the token. The respondent never
        // picks it, so a staff link cannot open the leadership questionnaire.
        state.linkToken = token;
        state.campaign = payload.campaign;
        state.grantedTrack = payload.track;

        if (state.campaign.status !== 'open') {
            elements.campaignEyebrow.textContent = 'Assessment closed';
            elements.campaignHeading.textContent = 'This assessment is no longer accepting responses';
            elements.campaignDetail.textContent = 'Contact whoever sent you this link.';
            setTrackAvailability([]);
            return;
        }

        elements.campaignEyebrow.textContent = 'Assessment for';
        elements.campaignHeading.textContent = state.campaign.org_name;
        elements.campaignDetail.textContent = state.grantedTrack === 'employee'
            ? 'Your individual answers are private and are never shown to your employer. Only anonymous, team-wide totals are shared. You will be asked to consent before starting.'
            : 'This is the leadership self-assessment of your organization\u2019s controls. You will be asked to consent before starting.';
        setTrackAvailability([state.grantedTrack]);
    } catch (error) {
        elements.campaignEyebrow.textContent = 'Link problem';
        elements.campaignHeading.textContent = 'This assessment link is not valid';
        elements.campaignDetail.textContent = error.message;
        setTrackAvailability([]);
    }
}

function setTrackAvailability(tracks) {
    // A respondent is granted exactly one track, so the other is hidden rather
    // than disabled: there is nothing they could do with it, and showing it
    // only raises questions about an assessment that is not theirs.
    const enabled = new Set(tracks);
    elements.startButtons.forEach((button) => {
        const available = enabled.has(button.dataset.start);
        button.disabled = !available;
        button.classList.toggle('hidden', !available);
    });
}

// ---------------------------------------------------------------------------
// Assessment flow
// ---------------------------------------------------------------------------

async function startAssessment(reportType) {
    if (!state.campaign) {
        showPage('home');
        return;
    }
    if (!state.campaign.tracks.includes(reportType)) {
        return;
    }

    // A new track means a new respondent record and fresh consent.
    if (state.reportType !== reportType) {
        state.respondentId = null;
        state.consentAgreed = false;
    }

    state.reportType = reportType;
    setActiveSegment(reportType);
    showPage('workspace');
    setStatus('Loading questionnaire...', '');

    try {
        const response = await fetch(`/api/questionnaire/${reportType}`);
        const payload = await response.json();
        if (!response.ok) {
            throw new Error(payload.message || 'Failed to load questionnaire.');
        }

        state.questions = flattenQuestions(reportType, payload.questionnaire);
        state.answers = new Array(state.questions.length).fill(null);
        state.currentQuestionIndex = 0;
        state.summary = null;

        elements.workspaceEyebrow.textContent = `${reportLabels[reportType]} assessment`;
        elements.workspaceTitle.textContent = `${reportLabels[reportType]} cyber hygiene assessment`;
        elements.workspaceSubtitle.textContent = 'Answer based on current practice. You can review everything before saving.';

        if (state.consentAgreed) {
            toggleSection('assessment');
            renderQuestion();
        } else {
            elements.consentCheckbox.checked = false;
            elements.consentError.classList.add('hidden');
            toggleSection('consent');
        }
        setStatus('Summary view will appear after you review and submit your responses.', '');
    } catch (error) {
        toggleSection('intro');
        setStatus(error.message, 'error');
    }
}

function acceptConsent() {
    if (!elements.consentCheckbox.checked) {
        elements.consentError.classList.remove('hidden');
        return;
    }
    state.consentAgreed = true;
    toggleSection('assessment');
    renderQuestion();
}

function flattenQuestions(reportType, questionnaire) {
    if (reportType === 'employee') {
        return questionnaire.questions.flatMap((category) =>
            category.questions.map((question) => ({
                category: category.category,
                question: question.question,
                answers: question.answers.map((answer) => ({
                    option: answer.option,
                    score: answer.score,
                })),
            }))
        );
    }

    return questionnaire.questions.map((question) => ({
        category: question.category,
        question: question.question,
        answers: question.answers.map((answer) => ({
            option: answer.text,
            score: answer.value,
        })),
    }));
}

function setActiveSegment(reportType) {
    elements.segments.forEach((segment) => {
        segment.classList.toggle('active', segment.dataset.start === reportType);
    });
}

function toggleSection(section) {
    elements.assessmentIntro.classList.toggle('hidden', section !== 'intro');
    elements.consentSection.classList.toggle('hidden', section !== 'consent');
    elements.assessmentSection.classList.toggle('hidden', section !== 'assessment');
    elements.reviewSection.classList.toggle('hidden', section !== 'review');
    elements.feedbackSection.classList.toggle('hidden', section !== 'feedback');
}

function renderQuestion() {
    const question = state.questions[state.currentQuestionIndex];
    const selectedScore = state.answers[state.currentQuestionIndex];

    elements.questionCategory.textContent = question.category;
    elements.questionTitle.textContent = question.question;
    elements.questionHelper.textContent = 'Choose the option that best matches today\'s reality. Stronger answers create stronger scores and fewer priority risks.';
    elements.progressText.textContent = `Question ${state.currentQuestionIndex + 1} of ${state.questions.length}`;
    elements.progressBar.style.width = `${((state.currentQuestionIndex + 1) / state.questions.length) * 100}%`;
    elements.backButton.disabled = state.currentQuestionIndex === 0;
    elements.nextButton.textContent = state.currentQuestionIndex === state.questions.length - 1 ? 'Review responses' : 'Next';
    elements.questionError.classList.add('hidden');

    elements.questionOptions.innerHTML = question.answers
        .map(
            (answer, index) => `
                <label class="option-card ${selectedScore === answer.score ? 'selected' : ''}">
                    <input type="radio" name="answer" value="${escapeHtml(answer.score)}" ${selectedScore === answer.score ? 'checked' : ''}>
                    <span>
                        <strong>Option ${index + 1}</strong>
                        <span>${escapeHtml(answer.option)}</span>
                    </span>
                </label>
            `
        )
        .join('');

    elements.questionOptions.querySelectorAll('input[name="answer"]').forEach((input) => {
        input.addEventListener('change', () => {
            state.answers[state.currentQuestionIndex] = Number(input.value);
            renderQuestion();
        });
    });
}

function handleBack() {
    if (state.currentQuestionIndex === 0) {
        return;
    }
    state.currentQuestionIndex -= 1;
    renderQuestion();
}

function handleNext() {
    if (state.answers[state.currentQuestionIndex] === null) {
        elements.questionError.classList.remove('hidden');
        return;
    }

    if (state.currentQuestionIndex < state.questions.length - 1) {
        state.currentQuestionIndex += 1;
        renderQuestion();
        return;
    }

    renderReview();
    toggleSection('review');
}

function renderReview() {
    const items = state.questions.map((question, index) => {
        const selectedScore = state.answers[index];
        const selectedAnswer = question.answers.find((answer) => answer.score === selectedScore);
        return `
            <article class="review-item">
                <p class="review-category">${escapeHtml(question.category)}</p>
                <h4>${escapeHtml(question.question)}</h4>
                <p class="review-answer">${escapeHtml(selectedAnswer ? selectedAnswer.option : 'No answer selected')}</p>
            </article>
        `;
    });

    elements.reviewList.innerHTML = items.join('');
}

function buildAssessmentPayload() {
    const responses = state.questions.map((question, index) => {
        const selectedScore = state.answers[index];
        const selectedAnswer = question.answers.find((answer) => answer.score === selectedScore) || null;
        return {
            question: question.question,
            category: question.category,
            answers: question.answers.map((answer) => ({
                option: answer.option,
                score: answer.score,
            })),
            selectedAnswer: selectedAnswer
                ? {
                      option: selectedAnswer.option,
                      score: selectedAnswer.score,
                  }
                : null,
        };
    });

    return {
        responses,
        metadata: {
            report_type: state.reportType,
            generated_from: 'web-interface',
        },
        consent: {
            agreed: state.consentAgreed,
            version: CONSENT_VERSION,
        },
    };
}

async function submitAssessment() {
    if (!state.campaign) {
        setStatus('No campaign context. Reopen your assessment link.', 'error');
        return;
    }
    if (!state.consentAgreed) {
        setStatus('Consent is required before your assessment can be saved.', 'error');
        return;
    }

    const payload = buildAssessmentPayload();
    elements.submitAssessmentButton.disabled = true;
    setStatus('Saving your assessment...', '');

    try {
        const response = await fetch(`/api/link/${state.linkToken}/submit`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.message || 'Failed to save assessment.');
        }

        state.respondentId = result.respondent_id;
        state.summary = summarizeAssessment(payload.responses);
        renderFeedback();
        toggleSection('feedback');
        setStatus('Assessment saved. Your summary is ready below.', 'success');
    } catch (error) {
        setStatus(error.message, 'error');
    } finally {
        elements.submitAssessmentButton.disabled = false;
    }
}

function summarizeAssessment(responses) {
    const categoryTotals = new Map();
    const strengths = [];
    const watchItems = [];
    const actions = [];
    let totalScore = 0;
    let maxScore = 0;

    responses.forEach((item) => {
        const selected = item.selectedAnswer;
        if (!selected) {
            return;
        }

        const possible = Math.max(...item.answers.map((answer) => answer.score));
        const scoreRatio = possible ? selected.score / possible : 0;

        if (!categoryTotals.has(item.category)) {
            categoryTotals.set(item.category, { earned: 0, possible: 0 });
        }
        const category = categoryTotals.get(item.category);
        category.earned += selected.score;
        category.possible += possible;

        totalScore += selected.score;
        maxScore += possible;

        if (scoreRatio >= 0.75) {
            strengths.push(`${item.question} — ${selected.option}`);
        } else {
            watchItems.push(`${item.question} — ${selected.option}`);
            actions.push(makeActionSuggestion(item));
        }
    });

    const categoryScores = Array.from(categoryTotals.entries()).map(([category, totals]) => ({
        category,
        score: totals.possible ? Math.round((totals.earned / totals.possible) * 100) : 0,
    }));
    categoryScores.sort((left, right) => left.score - right.score);

    return {
        overallScore: maxScore ? Math.round((totalScore / maxScore) * 100) : 0,
        maturityLabel: getMaturityLabel(maxScore ? (totalScore / maxScore) * 100 : 0),
        categoryScores,
        strengths: strengths.slice(0, 5),
        risks: watchItems.slice(0, 5),
        actions: dedupe(actions).slice(0, 6),
    };
}

function makeActionSuggestion(item) {
    const lowerQuestion = item.question.toLowerCase();
    if (lowerQuestion.includes('password')) {
        return 'Strengthen password controls and remove reuse or insecure storage patterns.';
    }
    if (lowerQuestion.includes('phishing') || lowerQuestion.includes('email')) {
        return 'Improve phishing awareness and verification habits with regular reminders or training.';
    }
    if (lowerQuestion.includes('incident')) {
        return 'Make incident reporting clearer and easier so issues are escalated faster.';
    }
    if (lowerQuestion.includes('backup')) {
        return 'Strengthen backup coverage, storage security, and restoration testing.';
    }
    if (lowerQuestion.includes('remote') || lowerQuestion.includes('vpn') || lowerQuestion.includes('wi-fi')) {
        return 'Tighten remote work protections, especially trusted connectivity and device use.';
    }
    return `Improve ${item.category.toLowerCase()} practices based on the weaker responses.`;
}

function dedupe(items) {
    return [...new Set(items)];
}

function getMaturityLabel(score) {
    if (score >= 80) return 'Strong';
    if (score >= 60) return 'Moderate';
    return 'Needs Attention';
}

function renderFeedback() {
    const summary = state.summary;
    elements.overallScore.textContent = `${summary.overallScore}%`;
    elements.maturityLabel.textContent = summary.maturityLabel;
    elements.topFocus.textContent = summary.categoryScores[0] ? summary.categoryScores[0].category : 'No gaps detected';
    elements.reportTypeLabel.textContent = reportLabels[state.reportType];
    elements.questionCountLabel.textContent = `${state.questions.length} responses reviewed`;

    renderDetailList(elements.strengthList, summary.strengths, 'Strong answers will appear here once identified.');
    renderDetailList(elements.riskList, summary.risks, 'No major risks detected from the current response set.');
    renderDetailList(elements.actionList, summary.actions, 'No immediate actions identified.');

    elements.categoryScoreList.innerHTML = summary.categoryScores
        .map((item) => {
            const tone = item.score >= 80 ? '#16a34a' : item.score >= 60 ? '#d97706' : '#dc2626';
            return `
                <div class="score-row">
                    <div class="score-head">
                        <strong>${escapeHtml(item.category)}</strong>
                        <span>${escapeHtml(item.score)}%</span>
                    </div>
                    <div class="score-bar"><div class="score-fill" style="width:${Number(item.score)}%; background:${tone};"></div></div>
                </div>
            `;
        })
        .join('');
}

function renderDetailList(element, items, emptyMessage) {
    if (!items.length) {
        element.innerHTML = `<li>${escapeHtml(emptyMessage)}</li>`;
        return;
    }
    element.innerHTML = items.map((item) => `<li>${escapeHtml(item)}</li>`).join('');
}

async function generateAndDownloadReport() {
    if (!state.linkToken || !state.respondentId) {
        setStatus('Save your assessment before generating a report.', 'error');
        return;
    }

    const base = `${state.linkToken}/report/${state.respondentId}`;
    elements.downloadButton.disabled = true;
    setStatus('Generating your PDF report. This can take a moment.', '');

    try {
        const response = await fetch(`/api/link/${base}`, { method: 'POST' });
        const payload = await response.json();
        if (!response.ok) {
            throw new Error(payload.message || 'Failed to generate the report.');
        }

        const link = document.createElement('a');
        link.href = `/api/link/${base}`;
        link.download = `${state.reportType}_cyber_hygiene_report.pdf`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);

        setStatus('PDF report generated successfully and download started.', 'success');
    } catch (error) {
        setStatus(error.message, 'error');
    } finally {
        elements.downloadButton.disabled = false;
    }
}

function setStatus(message, tone) {
    elements.reportStatus.textContent = message;
    elements.reportStatus.classList.remove('success', 'error');
    if (tone) {
        elements.reportStatus.classList.add(tone);
    }
}
