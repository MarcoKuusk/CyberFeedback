const state = {
    currentPage: 'home',
    reportType: null,
    campaignId: null,
    respondentId: null,
    questions: [],
    currentQuestionIndex: 0,
    answers: [],
    summary: null,
};

const ID_PATTERN = /^[0-9a-f]{32}$/;

const reportLabels = {
    employee: 'Employee',
    organization: 'Organization',
};

const elements = {};

document.addEventListener('DOMContentLoaded', () => {
    cacheElements();
    bindEvents();
    readCampaignFromUrl();
    showPage('home');
});

// Phase 1: campaign context arrives as a ?campaign=<id> query param. Phase 3
// replaces this with tokenized links; until then, an absent/invalid param falls
// back to a seeded local campaign created on first submit (see ensureCampaign).
function readCampaignFromUrl() {
    const params = new URLSearchParams(window.location.search);
    const campaign = params.get('campaign');
    if (campaign && ID_PATTERN.test(campaign)) {
        state.campaignId = campaign;
    }
}

async function ensureCampaign() {
    if (state.campaignId) {
        return state.campaignId;
    }
    // Dev fallback only (Phase 1): create a local campaign enabling both tracks
    // so the flow works without a link. Server binds 127.0.0.1; auth lands Phase 3.
    const response = await fetch('/api/campaigns', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ org_name: 'Local dev', tracks: ['employee', 'organization'] }),
    });
    const result = await response.json();
    if (!response.ok) {
        throw new Error(result.message || 'Failed to prepare a campaign.');
    }
    state.campaignId = result.campaign.campaign_id;
    return state.campaignId;
}

function cacheElements() {
    elements.pages = document.querySelectorAll('.page');
    elements.navLinks = document.querySelectorAll('[data-target]');
    elements.startButtons = document.querySelectorAll('[data-start]');
    elements.segments = document.querySelectorAll('.segment');
    elements.homeLink = document.getElementById('homeLink');
    elements.assessmentIntro = document.getElementById('assessmentIntro');
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
}

function showPage(pageId) {
    state.currentPage = pageId;
    elements.pages.forEach((page) => page.classList.toggle('page-active', page.id === pageId));
}

async function startAssessment(reportType) {
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
        state.respondentId = null;

        elements.workspaceEyebrow.textContent = `${reportLabels[reportType]} assessment`;
        elements.workspaceTitle.textContent = `${reportLabels[reportType]} cyber hygiene assessment`;
        elements.workspaceSubtitle.textContent = 'Answer based on current practice. You can review everything before saving.';

        toggleSection('assessment');
        renderQuestion();
        setStatus('Summary view will appear after you review and submit your responses.', '');
    } catch (error) {
        toggleSection('intro');
        setStatus(error.message, 'error');
    }
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
                    <input type="radio" name="answer" value="${answer.score}" ${selectedScore === answer.score ? 'checked' : ''}>
                    <span>
                        <strong>Option ${index + 1}</strong>
                        <span>${answer.option}</span>
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
                <p class="review-category">${question.category}</p>
                <h4>${question.question}</h4>
                <p class="review-answer">${selectedAnswer ? selectedAnswer.option : 'No answer selected'}</p>
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
    };
}

async function submitAssessment() {
    const payload = buildAssessmentPayload();
    setStatus('Saving your assessment...', '');

    try {
        const campaignId = await ensureCampaign();
        const response = await fetch(`/saveAssessmentData/${campaignId}/${state.reportType}`, {
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
        const entry = {
            category: item.category,
            question: item.question,
            answer: selected.option,
            score: selected.score,
            maxScore: possible,
        };

        if (!categoryTotals.has(item.category)) {
            categoryTotals.set(item.category, { earned: 0, possible: 0 });
        }
        const category = categoryTotals.get(item.category);
        category.earned += selected.score;
        category.possible += possible;

        totalScore += selected.score;
        maxScore += possible;

        if (scoreRatio >= 0.75) {
            strengths.push(`${item.question} – ${selected.option}`);
        } else {
            watchItems.push(`${item.question} – ${selected.option}`);
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
                        <strong>${item.category}</strong>
                        <span>${item.score}%</span>
                    </div>
                    <div class="score-bar"><div class="score-fill" style="width:${item.score}%; background:${tone};"></div></div>
                </div>
            `;
        })
        .join('');
}

function renderDetailList(element, items, emptyMessage) {
    if (!items.length) {
        element.innerHTML = `<li>${emptyMessage}</li>`;
        return;
    }
    element.innerHTML = items.map((item) => `<li>${item}</li>`).join('');
}

async function generateAndDownloadReport() {
    if (!state.reportType || !state.campaignId || !state.respondentId) {
        setStatus('Submit your assessment before generating a report.', 'error');
        return;
    }

    elements.downloadButton.disabled = true;
    setStatus('Generating your PDF report. This can take a moment.', '');

    const reportPath = `/${state.campaignId}/${state.reportType}/${state.respondentId}`;
    try {
        const response = await fetch(`/generateFeedback${reportPath}`, { method: 'POST' });
        const payload = await response.json();
        if (!response.ok) {
            throw new Error(payload.message || 'Failed to generate the report.');
        }

        const link = document.createElement('a');
        link.href = `/downloadReport${reportPath}`;
        link.download = `${state.reportType}_feedback_report.pdf`;
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
