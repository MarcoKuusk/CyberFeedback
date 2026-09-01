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
    meta.appendChild(el('span', null, `created: ${formatDate(campaign.created_at)}`));
    meta.appendChild(el('span', 'badge status', campaign.status || 'open'));
    (campaign.tracks || []).forEach((track) => meta.appendChild(el('span', 'badge', track)));
    row.appendChild(meta);

    const linksWrap = el('div', 'links-wrap');
    row.appendChild(linksWrap);
    loadLinks(campaign, linksWrap);

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

// The two links are different credentials with different audiences: one goes to
// every employee, the other only to leadership. They are labelled explicitly so
// they cannot be mixed up in an email — swapping them would put the leadership
// questionnaire in front of the whole company.
const TRACK_LINK_LABELS = {
    employee: {
        title: 'Staff link — send to every employee',
        note: 'Each person answers once and receives their own private report.',
    },
    organization: {
        title: 'Leadership link — send only to the leadership respondent',
        note: 'The top-down self-assessment of the organization\u2019s controls.',
    },
};

async function loadLinks(campaign, container) {
    container.replaceChildren(makeNote('Loading links...'));
    try {
        const response = await adminFetch(`/api/campaigns/${campaign.campaign_id}/links`);
        if (response.status === 403) {
            // Viewer role: rollups yes, distributable credentials no.
            container.replaceChildren();
            return;
        }
        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.message || 'Failed to load links.');
        }
        renderLinks(container, result.links || {}, result.viewer || null);
    } catch (error) {
        container.replaceChildren(makeNote(error.message));
    }
}

function renderLinks(container, links, viewer) {
    const rows = Object.keys(links).map((track) => {
        const url = links[track].url;
        const labels = TRACK_LINK_LABELS[track] || { title: `${track} link`, note: '' };

        const linkRow = el('div', 'link-row');
        linkRow.appendChild(el('span', 'link-label', labels.title));
        linkRow.appendChild(el('span', 'mono', url));

        const copyButton = el('button', 'button button-secondary small', 'Copy');
        copyButton.type = 'button';
        copyButton.addEventListener('click', () => copyLink(url, copyButton));
        linkRow.appendChild(copyButton);

        const open = el('a', 'button button-secondary small', 'Open');
        open.href = url;
        open.target = '_blank';
        open.rel = 'noopener';
        linkRow.appendChild(open);

        if (labels.note) {
            linkRow.appendChild(el('span', 'link-note', labels.note));
        }
        return linkRow;
    });

    if (viewer) {
        rows.push(buildViewerRow(viewer));
    }
    container.replaceChildren(...rows);
}

// Leadership's read credential for this campaign only. It is not a link they
// can click through to results: they open the admin page and enter it, and it
// unlocks nothing beyond this one campaign's rollups.
function buildViewerRow(viewer) {
    const row = el('div', 'link-row');
    row.appendChild(el('span', 'link-label', 'Leadership access code — send only to your client contact'));
    row.appendChild(el('span', 'mono', viewer.token));

    const copyButton = el('button', 'button button-secondary small', 'Copy code');
    copyButton.type = 'button';
    copyButton.addEventListener('click', () => copyLink(viewer.token, copyButton));
    row.appendChild(copyButton);

    row.appendChild(el(
        'span',
        'link-note',
        `They enter this at ${viewer.url} to see participation counts and download their organization's `
        + 'reports. It does not reveal any individual response.',
    ));
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
    // Counts are the shared truth for both roles. Respondent ids arrive only
    // for the operator, so the participation view degrades to numbers for a
    // viewer rather than being withheld entirely.
    const participation = result.participation || {};
    const submissions = result.submissions || null;
    const minAggregateN = result.min_aggregate_n;
    const tracks = (result.campaign && result.campaign.tracks) || Object.keys(participation);

    if (tracks.length === 0) {
        container.replaceChildren(makeNote('No tracks enabled for this campaign.'));
        return;
    }

    const blocks = tracks.map((track) => {
        const count = participation[track] || 0;
        const block = el('div', 'track-block');
        block.appendChild(el('p', 'track-title', `${track} — ${count} submission${count === 1 ? '' : 's'}`));

        if (count === 0) {
            block.appendChild(makeNote('No submissions yet.'));
        } else if (submissions) {
            (submissions[track] || []).forEach((entry) => block.appendChild(buildSubmissionRow(entry)));
        } else {
            block.appendChild(makeNote('Individual submissions are not shown in this role.'));
        }
        return block;
    });

    blocks.push(buildOrgReportsBlock(campaignId, tracks, participation, minAggregateN, container));
    container.replaceChildren(...blocks);
}

// Campaign-level org reports (Phase 2): aggregate, organization, combined.
// A mode's button is disabled (with a tooltip) when its required track is not
// enabled, so it's obvious why a report is unavailable.
function buildOrgReportsBlock(campaignId, tracks, participation, minAggregateN, container) {
    const hasEmployee = tracks.includes('employee');
    const hasOrg = tracks.includes('organization');
    const employeeCount = participation.employee || 0;

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

        // A plain <a href> cannot carry X-Admin-Token, so on any deployment with
        // a token configured it would 403. Fetch it and hand over a blob instead.
        const download = el('button', 'button button-secondary small', 'Download');
        download.type = 'button';
        download.addEventListener('click', () => downloadOrgReport(campaignId, mode, download, container));
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

// Deliberately read-only. An individual report belongs to the respondent who
// answered, and submissions carry no name, so there is no case in which the
// operator opening one is both useful and legitimate. Recovery after a failed
// batch is an ops task: scripts/regenerate_reports.py.
function buildSubmissionRow(entry) {
    const rowEl = el('div', 'submission-row');
    rowEl.appendChild(el('span', 'mono', entry.respondent_id));
    rowEl.appendChild(el('span', entry.has_report ? 'badge status' : 'badge',
        entry.has_report ? 'report ready' : 'no report'));
    return rowEl;
}

async function downloadOrgReport(campaignId, mode, button, container) {
    const original = button.textContent;
    button.disabled = true;
    button.textContent = 'Downloading...';
    try {
        const response = await adminFetch(`/downloadOrgReport/${campaignId}/${mode}`);
        if (!response.ok) {
            let message = 'That report has not been generated yet.';
            try {
                message = (await response.json()).message || message;
            } catch (parseError) {
                // Non-JSON error body; the default message is the useful one.
            }
            throw new Error(message);
        }

        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = `${mode}_report.pdf`;
        document.body.appendChild(anchor);
        anchor.click();
        document.body.removeChild(anchor);
        URL.revokeObjectURL(url);
    } catch (error) {
        container.appendChild(el('p', 'inline-error', error.message));
    } finally {
        button.disabled = false;
        button.textContent = original;
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
