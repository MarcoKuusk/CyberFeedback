// Local-only campaign admin. Drives the existing /api/campaigns endpoints.
// All registry-derived values (notably the user-supplied org_name) are rendered
// via textContent / DOM construction only — never interpolated into innerHTML —
// so a campaign name can never inject markup (XSS).

const els = {};

// The campaign API is admin-gated: a CYBERFEEDBACK_ADMIN_TOKEN if the server has
// one set, loopback-only otherwise. On loopback no token is needed, so the prompt
// below only ever appears when the server actually rejects the request. The token
// is held in memory only — never localStorage/sessionStorage/cookies — so it is
// not readable by any other script and does not survive a reload.
let adminToken = null;

async function adminFetch(url, options = {}) {
    const send = () => {
        const headers = { ...(options.headers || {}) };
        if (adminToken) {
            headers['X-Admin-Token'] = adminToken;
        }
        return fetch(url, { ...options, headers });
    };

    let response = await send();
    if (response.status === 403) {
        const entered = window.prompt('Admin token required for this server:');
        if (entered) {
            adminToken = entered.trim();
            response = await send();
        }
    }
    return response;
}


document.addEventListener('DOMContentLoaded', () => {
    els.form = document.getElementById('createForm');
    els.orgName = document.getElementById('orgName');
    els.createError = document.getElementById('createError');
    els.createStatus = document.getElementById('createStatus');
    els.refreshButton = document.getElementById('refreshButton');
    els.campaignList = document.getElementById('campaignList');

    els.form.addEventListener('submit', handleCreate);
    els.refreshButton.addEventListener('click', loadCampaigns);
    loadCampaigns();
});

function selectedTracks() {
    return Array.from(document.querySelectorAll('input[name="track"]:checked')).map((cb) => cb.value);
}

function setCreateStatus(message, tone) {
    els.createStatus.textContent = message || '';
    els.createStatus.classList.remove('success', 'error');
    if (tone) {
        els.createStatus.classList.add(tone);
    }
}

async function handleCreate(event) {
    event.preventDefault();
    const orgName = els.orgName.value.trim();
    const tracks = selectedTracks();

    if (!orgName || tracks.length === 0) {
        els.createError.classList.remove('hidden');
        return;
    }
    els.createError.classList.add('hidden');
    setCreateStatus('Creating campaign...', '');

    try {
        const response = await adminFetch('/api/campaigns', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ org_name: orgName, tracks }),
        });
        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.message || 'Failed to create campaign.');
        }
        els.form.reset();
        setCreateStatus(`Created campaign for "${result.campaign.org_name}".`, 'success');
        await loadCampaigns();
    } catch (error) {
        setCreateStatus(error.message, 'error');
    }
}

async function loadCampaigns() {
    els.campaignList.replaceChildren(makeNote('Loading campaigns...'));
    try {
        const response = await adminFetch('/api/campaigns');
        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.message || 'Failed to load campaigns.');
        }
        renderCampaigns(result.campaigns || []);
    } catch (error) {
        els.campaignList.replaceChildren(makeNote(error.message));
    }
}

function makeNote(text) {
    const p = document.createElement('p');
    p.className = 'empty-note';
    p.textContent = text;
    return p;
}

function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
}

function formatDate(iso) {
    try {
        const d = new Date(iso);
        return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
    } catch (error) {
        return iso;
    }
}

function renderCampaigns(campaigns) {
    if (!campaigns.length) {
        els.campaignList.replaceChildren(makeNote('No campaigns yet. Create one above.'));
        return;
    }

    const rows = campaigns
        .slice()
        .reverse() // newest first
        .map((campaign) => buildCampaignRow(campaign));
    els.campaignList.replaceChildren(...rows);
}

function buildCampaignRow(campaign) {
    const row = el('article', 'campaign-row');
    row.appendChild(el('h4', null, campaign.org_name));

    const meta = el('div', 'campaign-meta');
    meta.appendChild(el('span', 'mono', `id: ${campaign.campaign_id}`));
    meta.appendChild(el('span', null, `slug: ${campaign.org_slug}`));
    meta.appendChild(el('span', null, `created: ${formatDate(campaign.created_at)}`));
    meta.appendChild(el('span', 'badge status', campaign.status || 'open'));
    (campaign.tracks || []).forEach((track) => meta.appendChild(el('span', 'badge', track)));
    row.appendChild(meta);

    const link = `${window.location.origin}/?campaign=${campaign.campaign_id}`;
    const linkRow = el('div', 'link-row');
    linkRow.appendChild(el('span', 'link-label', 'Respondent link'));
    linkRow.appendChild(el('span', 'mono', link));

    const copyButton = el('button', 'button button-secondary small', 'Copy link');
    copyButton.type = 'button';
    copyButton.addEventListener('click', () => copyLink(link, copyButton));
    linkRow.appendChild(copyButton);

    const open = el('a', 'button button-secondary small', 'Open');
    open.href = link;
    open.target = '_blank';
    open.rel = 'noopener';
    linkRow.appendChild(open);
    row.appendChild(linkRow);

    // Submissions panel (lazy-loaded; this is where saved assessments show up).
    const subsWrap = el('div', 'submissions-wrap hidden');
    const actions = el('div', 'row-actions');
    const viewButton = el('button', 'button button-secondary small', 'View submissions');
    viewButton.type = 'button';
    viewButton.addEventListener('click', async () => {
        const nowHidden = subsWrap.classList.toggle('hidden');
        viewButton.textContent = nowHidden ? 'View submissions' : 'Hide submissions';
        if (!nowHidden) {
            await refreshSubmissions(campaign.campaign_id, subsWrap);
        }
    });
    actions.appendChild(viewButton);
    row.appendChild(actions);
    row.appendChild(subsWrap);

    return row;
}

async function refreshSubmissions(campaignId, container) {
    container.replaceChildren(makeNote('Loading submissions...'));
    try {
        const response = await adminFetch(`/api/campaigns/${campaignId}/submissions`);
        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.message || 'Failed to load submissions.');
        }
        renderSubmissions(container, campaignId, result);
    } catch (error) {
        container.replaceChildren(makeNote(error.message));
    }
}

function renderSubmissions(container, campaignId, result) {
    const submissions = result.submissions || {};
    const minAggregateN = result.min_aggregate_n;
    const tracks = Object.keys(submissions);
    if (tracks.length === 0) {
        container.replaceChildren(makeNote('No tracks enabled for this campaign.'));
        return;
    }
    const blocks = tracks.map((track) => {
        const rows = submissions[track] || [];
        const block = el('div', 'track-block');
        block.appendChild(el('p', 'track-title', `${track} — ${rows.length} submission${rows.length === 1 ? '' : 's'}`));
        if (rows.length === 0) {
            block.appendChild(makeNote('No submissions yet.'));
        } else {
            rows.forEach((entry) => block.appendChild(buildSubmissionRow(campaignId, track, entry, container)));
        }
        return block;
    });
    blocks.push(buildOrgReportsBlock(campaignId, submissions, minAggregateN, container));
    container.replaceChildren(...blocks);
}

// Campaign-level org reports (Phase 2): aggregate, organization, combined.
// A mode's button is disabled (with a tooltip) when its required track is not
// enabled, so it's obvious why a report is unavailable.
function buildOrgReportsBlock(campaignId, submissions, minAggregateN, container) {
    const hasEmployee = Object.prototype.hasOwnProperty.call(submissions, 'employee');
    const hasOrg = Object.prototype.hasOwnProperty.call(submissions, 'organization');
    const employeeCount = (submissions.employee || []).length;

    const block = el('div', 'track-block');
    block.appendChild(el('p', 'track-title', 'Organization reports'));

    if (typeof minAggregateN === 'number') {
        const note = employeeCount >= minAggregateN
            ? `${employeeCount} employee submissions — above the ${minAggregateN}-respondent anonymity threshold.`
            : `${employeeCount} of ${minAggregateN} employee submissions — the aggregate is withheld until the anonymity threshold is met.`;
        block.appendChild(makeNote(note));
    }

    const modes = [
        { mode: 'aggregate', label: 'Aggregate', enabled: hasEmployee, reason: 'Requires the employee track.' },
        { mode: 'organization', label: 'Organization', enabled: hasOrg, reason: 'Requires the organization track.' },
        { mode: 'combined', label: 'Combined', enabled: hasEmployee && hasOrg, reason: 'Requires both tracks.' },
    ];

    modes.forEach(({ mode, label, enabled, reason }) => {
        const rowEl = el('div', 'submission-row');
        rowEl.appendChild(el('span', 'mono', mode));

        const genButton = el('button', 'button button-secondary small', `Generate ${label}`);
        genButton.type = 'button';
        if (!enabled) {
            genButton.disabled = true;
            genButton.title = reason;
        } else {
            genButton.addEventListener('click', () => generateOrgReport(campaignId, mode, genButton, container));
        }
        rowEl.appendChild(genButton);

        const download = el('a', 'button button-secondary small', 'Download');
        download.href = `/downloadOrgReport/${campaignId}/${mode}`;
        download.target = '_blank';
        download.rel = 'noopener';
        rowEl.appendChild(download);

        block.appendChild(rowEl);
    });

    return block;
}

async function generateOrgReport(campaignId, mode, button, container) {
    const original = button.textContent;
    button.disabled = true;
    button.textContent = 'Generating...';
    try {
        const response = await adminFetch(`/generateOrgReport/${campaignId}/${mode}`, { method: 'POST' });
        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.message || 'Failed to generate report.');
        }
        await refreshSubmissions(campaignId, container);
    } catch (error) {
        button.disabled = false;
        button.textContent = original;
        container.appendChild(el('p', 'inline-error', error.message));
    }
}

function buildSubmissionRow(campaignId, track, entry, container) {
    const rowEl = el('div', 'submission-row');
    rowEl.appendChild(el('span', 'mono', entry.respondent_id));
    rowEl.appendChild(el('span', entry.has_report ? 'badge status' : 'badge',
        entry.has_report ? 'report ready' : 'no report'));

    const genButton = el('button', 'button button-secondary small', entry.has_report ? 'Regenerate' : 'Generate report');
    genButton.type = 'button';
    genButton.addEventListener('click', () => generateReport(campaignId, track, entry.respondent_id, genButton, container));
    rowEl.appendChild(genButton);

    if (entry.has_report) {
        const download = el('a', 'button button-secondary small', 'Download');
        download.href = `/downloadReport/${campaignId}/${track}/${entry.respondent_id}`;
        download.target = '_blank';
        download.rel = 'noopener';
        rowEl.appendChild(download);
    }
    return rowEl;
}

async function generateReport(campaignId, track, respondentId, button, container) {
    const original = button.textContent;
    button.disabled = true;
    button.textContent = 'Generating...';
    try {
        const response = await adminFetch(`/generateFeedback/${campaignId}/${track}/${respondentId}`, { method: 'POST' });
        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.message || 'Failed to generate report.');
        }
        await refreshSubmissions(campaignId, container); // reflect the new report + download link
    } catch (error) {
        button.disabled = false;
        button.textContent = original;
        container.appendChild(el('p', 'inline-error', error.message));
    }
}

async function copyLink(link, button) {
    const original = button.textContent;
    try {
        await navigator.clipboard.writeText(link);
        button.textContent = 'Copied';
    } catch (error) {
        button.textContent = 'Copy failed';
    }
    setTimeout(() => { button.textContent = original; }, 1500);
}
