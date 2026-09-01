# Consent and Participant Communication

Three things live here: the consent text participants actually see, the
invitation to send them, and what must be finalized before this is used for
research.

---

## Status: the consent version is still a draft

`CONSENT_VERSION` in [scripts.js](../src/webinterface/scripts.js) is
`'1.0-draft'`, and that string is written into every stored submission.

Every record collected before it is bumped is marked as having agreed to a
*draft* consent text. For a commercial engagement that is untidy. For thesis
data it is worse — a reviewer can reasonably object that participants consented
to something not yet approved.

**Before the first real engagement:**

1. Finalize the wording below (and in `index.html`) with your ethics reviewer.
2. Change `CONSENT_VERSION` to `'1.0'`.
3. Do not edit the text afterwards without bumping the version. The point of
   recording a version is that you can say precisely what each participant
   agreed to.

---

## What participants see

Shown before the first question. Nothing is stored unless the box is ticked, and
the check is enforced server-side as well as in the browser — a submission
without recorded consent is rejected at the storage layer, not merely hidden in
the UI.

> **Your individual answers are private.** Your employer never sees your answers
> or your personal report. Only you receive your own report.
>
> - Your answers are combined with your colleagues' into an **anonymous team
>   summary**. No category is reported unless at least five people have
>   answered, so individuals cannot be identified.
> - Your answers are also used, in anonymous form, for **academic research** (a
>   master's thesis on cyber hygiene in small and medium organizations). Your
>   name and your employer's name are never published.
> - To write your report, your answers are sent to **OpenAI**, an external AI
>   service, in a form that does not include your name.
> - No name, email address, or job title is collected by this tool.
> - Participation is **voluntary**. You may stop at any point before submitting,
>   and nothing is saved until you submit.

Every claim above is enforced in code, not just asserted:

| Claim | Where it holds |
|---|---|
| Employer never sees your answers | Leadership role receives counts only; no individual endpoint accepts it |
| Minimum of five | `MIN_AGGREGATE_N` in [report_analysis.py](../src/utils/report_analysis.py) |
| No name or email collected | No free-text input exists in either questionnaire |
| Nothing saved until you submit | Answers are held in browser memory until the submit call |

If you change the product, re-check this table. A consent promise that quietly
stops being true is the worst failure this project could have.

### If the engagement is not for research

Remove the academic-research bullet and use a separate consent version (e.g.
`'1.0-commercial'`). Do not leave a research clause in front of a client's staff
if their data will never be used that way.

---

## Invitation to staff

Send from someone inside the company, not from you. A message from an outside
party asking employees about their security habits looks exactly like phishing.

> **Subject: Cyber hygiene self-check — 10 minutes, private to you**
>
> Hi all,
>
> We're running a short cyber hygiene self-assessment. It takes about ten
> minutes on your phone or laptop.
>
> **What you get:** your own personal report with practical recommendations,
> generated from your answers.
>
> **What we get:** an anonymous, team-wide summary. Not your individual answers —
> those are never shown to me or anyone else in management. The tool doesn't
> collect your name or email, and it won't report any category unless at least
> five people have answered.
>
> Taking part is voluntary. There are no right answers, and nothing here feeds
> into any review — an honest answer is genuinely more useful than a flattering
> one.
>
> **Your link:** <STAFF LINK>
> **Please complete by:** <DATE>
>
> One tip: your report downloads as a PDF at the end. Save it — it can't be
> recovered afterwards, because we have no way to tell which report was yours.

Replace `<STAFF LINK>` with the **staff** link from the admin console. Check the
label before you paste: the leadership link opens a different questionnaire.

## Invitation to the leadership respondent

> **Subject: Organizational security self-assessment**
>
> Hi <NAME>,
>
> Alongside the staff assessment, we need one organization-level questionnaire
> completed by someone who knows what controls are actually in place — backups,
> patching, access management, incident response.
>
> This one is not anonymous in the same way: it describes the organization
> rather than an individual, and its results appear in the leadership report.
>
> **Your link:** <LEADERSHIP LINK>
>
> Where you're unsure, answer what is genuinely true rather than what should be
> true. The value of the final report comes from comparing this against what
> staff report doing — an inflated answer here just produces a gap that isn't
> real.

---

## Practical notes

**People will ask whether it is really anonymous.** The honest answer: the tool
collects no name or email, and management receives only counts and aggregates.
The caveat worth volunteering is that in a very small team, a determined manager
could narrow things down by who was asked and when — which is exactly why the
five-person threshold exists.

**People will ask if it affects their review.** That is the client's promise to
make, not yours. Ask them to state it explicitly in the invitation.

**Someone will lose their report.** Say up front that it cannot be recovered.
This is a consequence of not knowing who they are.
