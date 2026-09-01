# Operator Runbook — Running an Engagement

How to take one client organization from "yes, we'll try it" to three delivered
reports. Nothing here requires you to be on site or to touch a participant's
device.

---

## Roles and credentials

| Who | Holds | Can do |
|---|---|---|
| **You** (operator) | `CYBERFEEDBACK_ADMIN_TOKEN` | Everything, across all clients |
| **Client leadership** | that campaign's viewer code | Participation counts and their own three reports |
| **Each employee** | the staff link | Answer once, get their own private report |
| **Leadership respondent** | the leadership link | Complete the organizational self-assessment |

The staff link and the leadership link are **different URLs** and are not
interchangeable. Sending the leadership link to everyone would put the
organizational self-assessment in front of the whole company. The admin console
labels them explicitly for this reason — copy them one at a time.

---

## Before the first client

- [ ] Deployment is live over HTTPS ([DEPLOYMENT.md](DEPLOYMENT.md))
- [ ] Full-disk encryption enabled on the host
- [ ] Backups running and encrypted
- [ ] `OPENAI_API_KEY` set, and one test report generated end to end
- [ ] Ethics approval in hand, if the data will be used for the thesis
- [ ] Consent text finalized and `CONSENT_VERSION` bumped off `1.0-draft`
      ([scripts.js](../src/webinterface/scripts.js), [CONSENT.md](CONSENT.md))
- [ ] [DATA_HANDLING.md](DATA_HANDLING.md) reviewed, with the OpenAI section
      filled in with what is actually true for your account

That consent checkbox matters: every stored submission records the version
agreed to, and `1.0-draft` in a research dataset means the consent was never
finalized.

---

## 1. Agree the scope with the client

Decide with them:

- **Which tracks.** Employee only, leadership only, or both. Both is the strong
  offer, because the combined report is the thing neither assessment produces
  alone.
- **Who is the leadership respondent.** One person who genuinely knows the
  controls — usually IT lead or an owner in a smaller company.
- **How many staff.** Under 5 employee respondents, no aggregate is produced
  at all. Say this before they agree, not after.
- **The deadline** for staff to respond.
- **The deletion date.**

Hand them [DATA_HANDLING.md](DATA_HANDLING.md) at this stage. It answers the
questions that otherwise stall the conversation for a week.

## 2. Create the campaign

Open `/admin`, enter your operator token when prompted, and create a campaign
with the client's real organization name and the agreed tracks.

You get three credentials. Route them deliberately:

| Credential | Goes to |
|---|---|
| Staff link (`/c/…`) | Every employee |
| Leadership link (`/c/…`) | The one leadership respondent |
| Leadership access code | Your client contact, if they want their own access |

Never paste all three into one email.

## 3. Invite participants

Send the staff link with the participant text from [CONSENT.md](CONSENT.md).
Have it come from someone inside the company — a message from an outside vendor
asking about security habits reads as phishing, which is a memorably bad way to
begin a security engagement.

Ask the client to state plainly that participation is voluntary and that
individual answers are not visible to management. Response quality depends on
people believing it, and it happens to be true.

## 4. Watch participation

In `/admin`, expand a campaign and choose **View submissions**. You see counts
per track and opaque respondent ids — never answers.

Chase the number, not the individuals. You cannot tell who has responded, by
design, so "we're at 12 of 30" is the only nudge available. That is the correct
amount of pressure.

Wait for at least 5 employee responses. Below that the aggregate is withheld.

## 5. Close and generate

When the deadline passes, generate the reports from the campaign's
**Organization reports** block:

- **Aggregate** — the anonymized employee picture
- **Organization** — leadership's own self-assessment
- **Combined** — the gap between what leadership believes and what staff report

Generate all three, then read them before anyone else does. The AI writes the
narrative; you are accountable for it. Check the combined report especially:
categories with no employee counterpart must read as "leadership-only", not as
a score of zero.

## 6. Deliver

Present the combined report first — the gap is the insight they are paying for.
The aggregate and the self-assessment are the evidence behind it.

Employees already have their individual reports; you have nothing to deliver to
them and no way to reach them individually.

## 7. Close out

- Confirm the deletion date in writing.
- On that date: `python scripts/delete_org_data.py --org <slug>`, then delete
  the backups holding copies, then confirm in writing.
- If the data is going into the thesis, export before deleting:
  `python scripts/export_research_data.py --out research_export`

Export first. Deletion is irreversible and the export is anonymized, so the
order matters and only works one way.

---

## When something goes wrong

**Reports fail for everyone.** Almost always `OPENAI_API_KEY` unset or an
invalid model name. Submissions are safe on disk regardless — only PDFs are
missing. Fix the cause, then:

```bash
python scripts/regenerate_reports.py --campaign <campaign_id> --missing-only
```

**One report failed.** Same command; it only rebuilds what is missing.

**A respondent lost their report.** You cannot recover it for them. Their report
is reachable only from their own browser session, and submissions carry no name,
so there is no way to identify which record is theirs. They can retake the
assessment. Tell people to save the PDF when it downloads.

**Someone submitted twice.** Both records count toward the aggregate. There is
no dedupe, because there is no identity to dedupe on. For small teams, mention
this to the client rather than quietly letting it skew the numbers.

**The client asks to see an individual employee's answers.** You cannot, and
neither can they. This is the guarantee that got their staff to answer honestly.
Say so plainly — it is a feature of the product, not a limitation of it.
