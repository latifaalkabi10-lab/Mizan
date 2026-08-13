Build a complete, professional, working web application called:

MIZAN
Procurement Intelligence

Tagline:

"Balance every bid. Defend every decision."

MIZAN is an AI-powered, evidence-grounded supplier bid evaluation system for ADNOC Upstream Procurement & Contracts.

The system helps a procurement engineer evaluate supplier bids using the official evaluation methodology contained in the provided challenge dataset.

IMPORTANT:
This is a prototype created for the AI Innovation Challenge. Do not present MIZAN as an official ADNOC product or claim ADNOC endorsement.

==================================================
1. CORE PRODUCT PURPOSE
==================================================

MIZAN helps a procurement engineer:

- Review tender requirements
- Search the provided procurement dataset
- Check mandatory supplier requirements
- Evaluate technical capability
- Evaluate commercial pricing
- Evaluate HSE performance
- Evaluate ICV contribution
- Compare suppliers
- Identify procurement risks
- Escalate serious cases to a human
- Generate an evidence-grounded recommendation report

The key product principle is:

"Evaluate supplier bids with evidence, not assumptions."

The system must NOT automatically award a contract.

The final workflow is:

AI Evaluation
→ AI Recommendation
→ Human Procurement Engineer Review
→ Final Human Decision

==================================================
2. DATASET & KNOWLEDGE BASE
==================================================

Use the provided challenge dataset as the primary knowledge source.

Relevant files include:

- RFP_ADNOC-LCIG_2026-0412_Produced_Water_Treatment.pdf
- Bid_Submission_Tracker_2026-0412.xlsx
- Any additional supplier bid documents provided with the challenge

The main RFP is:

ADNOC-LCIG/RFP/2026-0412

Scope:

Supply, Installation & Commissioning of a Produced Water Treatment Package

Location:

Bu Hasnah Field — CPF-2

The RFP is the authoritative source for:
- Tender requirements
- Mandatory submission requirements
- Technical evaluation
- Commercial evaluation
- HSE evaluation
- ICV evaluation
- Scoring methodology

The Bid Submission Tracker should be searchable for supplier/bid submission information.

IMPORTANT DATA INTEGRITY RULE:

Never invent:
- Supplier prices
- Supplier scores
- Technical capabilities
- HSE statistics
- ICV percentages
- Certifications
- Submitted documents
- Supplier relationships
- Tender results

If information is not in the provided dataset, say:

"Not found in the provided challenge dataset. I cannot verify this information."

If demo data is required, clearly label it:

"SIMULATED DEMO DATA — NOT AN ACTUAL ADNOC BID RESULT."

==================================================
3. MULTI-AGENT ARCHITECTURE
==================================================

Build a REAL multi-agent workflow.

The following agents must exist and actually be reachable:

1. Evidence & Retrieval Agent
2. Compliance & Screening Agent
3. Technical Evaluation Agent
4. Commercial Evaluation Agent
5. HSE Evaluation Agent
6. ICV Evaluation Agent
7. Risk & Human Escalation Agent
8. Recommendation & Report Agent

Do NOT create fake agent cards that merely look active.

Agent outputs must genuinely feed into downstream agents.

The workflow is:

RFP + BID DATA
        ↓
Evidence & Retrieval Agent
        ↓
Compliance & Screening Agent
        ↓
 ┌──────────────┬──────────────┬──────────────┐
 ↓              ↓              ↓              ↓
Technical     Commercial       HSE            ICV
Agent         Agent            Agent          Agent
 └──────────────┴──────────────┴──────────────┘
                       ↓
              Risk & Escalation Agent
                       ↓
             Recommendation Agent
                       ↓
             Procurement Report
                       ↓
              Human Approval

==================================================
4. REQUIRED TOOLS
==================================================

Implement working tools.

Minimum tools:

search_knowledge_base(query)

calculate_commercial_score(lowest_price, supplier_price)

calculate_icv_score(icv_percentage)

calculate_total_score(technical, commercial, hse, icv)

escalate_to_human(case_details)

The tools must actually execute during system operation.

Do not create unused tools.

For arithmetic, prefer deterministic calculation functions rather than asking the LLM to perform important calculations itself.

==================================================
5. EVIDENCE & RETRIEVAL AGENT
==================================================

ROLE:

Retrieve accurate evidence from the provided challenge dataset.

The agent must use:

search_knowledge_base(query)

The retrieval system must search the actual uploaded documents.

For every important finding return:

FACT:
[verified fact]

SOURCE:
[document]

LOCATION:
[page / section / spreadsheet row when available]

EVIDENCE:
[supporting information]

CONFIDENCE:
Verified / Partially Verified / Not Found

The retrieval agent passes a structured evidence package to the Compliance Agent and evaluation agents.

Never answer from general model knowledge when the requested fact should come from the dataset.

==================================================
6. COMPLIANCE & SCREENING AGENT
==================================================

ROLE:

Determine whether each supplier satisfies mandatory submission and minimum qualification requirements before scoring.

Check the RFP's D1-D9 requirements, including applicable:
- Company information/licence
- Technical proposal
- Commercial proposal
- Delivery schedule
- HSE statistics
- ICV certificate
- Financial statements
- Bid bond/bank guarantee
- Warranty statement

Also check mandatory technical requirements specified by the RFP.

Output:

Supplier:
Mandatory Status:
PASS / FAIL / CONDITIONAL / UNKNOWN

Missing Requirements:
[List]

Technical Minimum:
PASS / FAIL / UNKNOWN

Evidence:
[Sources]

Reason:
[Explanation]

The result must feed the Technical, Commercial, HSE, ICV and Risk agents.

==================================================
7. TECHNICAL EVALUATION AGENT
==================================================

ROLE:

Evaluate technical capability according to the RFP.

Technical evaluation = 40 points.

Use the exact technical criteria and scoring bands in the RFP.

Evaluate the applicable criteria, including:

T1 Process capacity & performance
T2 Technology track record
T3 Company experience & organisation
T4 Delivery schedule

Do not invent scores.

Output:

Supplier
Technical Compliance
T1 Score
T2 Score
T3 Score
T4 Score
Technical Total /40
Strengths
Weaknesses
Missing Evidence
Sources

If evidence is insufficient:

"Insufficient evidence to calculate this criterion."

==================================================
8. COMMERCIAL EVALUATION AGENT
==================================================

ROLE:

Evaluate supplier pricing according to the RFP's commercial methodology.

Commercial evaluation = 30 points.

Use the RFP formula:

Commercial Score =
30 × (lowest qualifying evaluated price / supplier evaluated price)

Only use the lowest qualifying evaluated price according to the RFP methodology.

Handle currency conversion according to the RFP.

Use:

calculate_commercial_score()

Output:

Supplier
Evaluated Price
Currency
AED Equivalent
Lowest Qualifying Price
Commercial Score /30
Commercial Notes
Sources

IMPORTANT:

The cheapest supplier is NOT automatically the recommended supplier.

Commercial score is only one part of the total evaluation.

==================================================
9. HSE EVALUATION AGENT
==================================================

ROLE:

Evaluate supplier HSE performance using the RFP methodology.

HSE evaluation = 15 points.

Evaluate the RFP's applicable criteria, including:

H1 Safety performance / TRIR
H2 HSE management certification

Output:

Supplier
TRIR
TRIR Score
Certification
Certification Score
HSE Total /15
HSE Risks
Sources

Never invent HSE information.

==================================================
10. ICV EVALUATION AGENT
==================================================

ROLE:

Evaluate In-Country Value as an explicit supplier evaluation factor.

ICV evaluation = 15 points.

Use the RFP's actual ICV methodology.

Where the certified ICV percentage is available, use:

ICV Score =
15 × min(certified ICV %, 60) ÷ 60

Use:

calculate_icv_score()

For each supplier display:

ICV Score /15
Certified ICV %
Local UAE Spending
UAE Manufacturing
Emiratization
ICV Status
Evidence

If a requested value does not exist in the dataset:

"Not available in the provided dataset."

ICV must influence the final recommendation alongside:
- Technical
- Commercial
- HSE
- Risk

The system must be able to explain how ICV affected the ranking.

==================================================
11. RISK & HUMAN ESCALATION AGENT
==================================================

ROLE:

Identify serious procurement risks and determine whether human review is required.

Escalate when:
- Mandatory information is missing
- Mandatory requirements fail
- Technical compliance cannot be verified
- Important supplier information conflicts
- ICV information cannot be verified
- HSE information is materially incomplete
- Commercial information is contradictory
- An important calculation cannot be completed reliably
- Agents materially disagree
- The recommendation depends on unsupported evidence

Use:

escalate_to_human(case_details)

Output:

Risk Level:
LOW / MEDIUM / HIGH

Human Review Required:
YES / NO

Reason:
Evidence:
Affected Supplier:
Recommended Human Action:

IMPORTANT:

An ordinary, fully supported evaluation must NOT trigger escalation.

A serious or uncertain case MUST trigger the escalation tool.

When escalation happens, the recommendation must be marked:

HUMAN REVIEW REQUIRED

==================================================
12. RECOMMENDATION & REPORT AGENT
==================================================

ROLE:

Combine all agent outputs and produce the final evidence-grounded procurement recommendation.

Inputs:

Evidence
Compliance
Technical
Commercial
HSE
ICV
Risk
Escalation Status

Calculate:

Total =
Technical + Commercial + HSE + ICV

Maximum = 100

Use:

calculate_total_score()

Create a supplier ranking from highest eligible score to lowest.

For each supplier display:

Supplier
Compliance
Technical /40
Commercial /30
HSE /15
ICV /15
Total /100
Risk

Then produce:

MIZAN RECOMMENDATION

Recommended Supplier:
Overall Score:

WHY?

Explain the ranking using evidence.

TRADE-OFF ANALYSIS:

Explain cases such as:

"Supplier B has the lower evaluated price and therefore receives the strongest commercial score. However, Supplier A achieves stronger technical, HSE and ICV results, resulting in the higher overall evaluation."

Only say this when supported by actual data.

Do not claim:

"ADNOC awarded the contract."

Use:

"AI Recommendation"

or:

"Highest-ranked supplier based on the provided evaluation methodology."

==================================================
13. HUMAN DECISION
==================================================

The final system must always preserve human control.

Final flow:

AI Recommendation
↓
Human Procurement Engineer Review
↓
Approve Recommendation
OR
Request Clarification
OR
Reject Recommendation

The system does not automatically award contracts.

==================================================
14. BRAND — MIZAN
==================================================

PRODUCT NAME:

MIZAN

SUBTITLE:

Procurement Intelligence

TAGLINE:

Balance every bid. Defend every decision.

MIZAN represents the balanced evaluation of:

TECHNICAL
+
COMMERCIAL
+
HSE
+
ICV
+
RISK

The name MIZAN is the product identity for this challenge.

Do not present it as an official ADNOC product.

==================================================
15. ADNOC OPENING ANIMATION
==================================================

When the website loads, show a premium splash screen.

Sequence:

1. Clean white/off-white background.
2. Official approved ADNOC logo centered.
3. Subtle fade-in.
4. Brief hold.
5. Smooth fade/transition.
6. MIZAN appears:

MIZAN

Procurement Intelligence

Balance every bid.
Defend every decision.

7. Transition into the dashboard.

Duration:
Approximately 1.5–2 seconds.

The animation must be:
- Smooth
- Premium
- Professional
- Minimal

Do NOT use:
- Spinning logos
- Particle effects
- Neon
- Glowing AI brains
- Excessive zoom
- Loud transitions
- Dark cinematic effects

Do not recreate or modify the official ADNOC logo. Use the approved/provided asset.

==================================================
16. COLOR & VISUAL SYSTEM
==================================================

The website should feel ADNOC-inspired, bright, premium and professional.

DO NOT make the website predominantly black or extremely dark.

Color balance:

65–70%
White / off-white / light surfaces

20–25%
Navy / charcoal

5–10%
Status colors

Primary:
- ADNOC-inspired navy
- White
- Off-white
- Light gray

Supporting:
- Charcoal text
- Muted blue
- Green = verified/pass
- Amber = warning/review
- Red = critical risk/escalation

Use navy primarily for:
- Sidebar
- Main navigation
- Primary buttons
- Selected states
- Branding

Use white/light gray for:
- Main workspace
- Cards
- Tables
- Reports
- Evidence panels

Avoid excessive glassmorphism.

==================================================
17. MAIN APPLICATION HEADER
==================================================

Create a persistent top header.

LEFT:

Official ADNOC logo

Next to it:

MIZAN
Procurement Intelligence

RIGHT:

● System Operational

Procurement Engineer

Settings/Profile

The header remains visible across the application.

==================================================
18. SIDEBAR NAVIGATION
==================================================

Use a navy sidebar with clear icons.

Navigation:

Dashboard
Tenders
Bid Evaluations
Suppliers
Risk & Escalations
Reports
Agent Activity

Bottom:

System Status
Settings

The sidebar should be visually strong but not overpower the bright main workspace.

==================================================
19. DASHBOARD
==================================================

Header:

MIZAN
Procurement Intelligence

"Evaluate supplier bids with evidence, not assumptions."

KPI cards:

ACTIVE TENDERS
BIDS RECEIVED
EVALUATIONS IN PROGRESS
HUMAN REVIEWS

Featured evaluation:

ADNOC-LCIG/RFP/2026-0412

Produced Water Treatment Package
Bu Hasnah Field — CPF-2

10 Supplier Bids
18 Documents
Ready for Evaluation

Button:

START AI EVALUATION

==================================================
20. BID EVALUATION WORKSPACE
==================================================

This is the centerpiece of the website.

Header:

MIZAN Evaluation

ADNOC-LCIG/RFP/2026-0412

Display:

10 Bids
18 Documents
Evaluation Status

Then show the real agent pipeline:

🔎 Evidence
↓
✓ Compliance
↓
🔧 Technical
💰 Commercial
🦺 HSE
🇦🇪 ICV
↓
⚠ Risk
↓
📝 Recommendation

Each agent should show:

● Processing
✓ Complete
⚠ Review Required
🚨 Escalated

The status must reflect actual backend execution.

==================================================
21. SUPPLIER COMPARISON
==================================================

Create a professional comparison table.

Columns:

Supplier
Compliance
Technical /40
Commercial /30
HSE /15
ICV /15
Total /100
Risk

Highlight the highest-ranked eligible supplier.

Create a prominent section:

MIZAN RECOMMENDATION

Supplier:
Score:

WHY THIS SUPPLIER?

Show the evidence-backed reasoning.

==================================================
22. SUPPLIER DETAIL VIEW
==================================================

When the user clicks a supplier, show:

Supplier Overview

Compliance Status

Technical Evaluation
Commercial Evaluation
HSE Evaluation
ICV Evaluation
Risk

Overall Score

Then show an evidence panel.

The user should be able to understand exactly how the supplier reached its score.

==================================================
23. ICV VISUAL EXPERIENCE
==================================================

Create a dedicated ICV card/panel.

MIZAN
In-Country Value

Show:

ICV SCORE /15

Certified ICV %

UAE Spending

UAE Manufacturing

Emiratization

ICV Status

Then:

HOW ICV AFFECTED THE DECISION

The AI explains how the supplier's ICV contribution affected the total score and ranking.

Do not exaggerate the importance of ICV beyond the RFP's actual 15-point weighting.

==================================================
24. "WHY THIS SUPPLIER?" EXPERIENCE
==================================================

This should be one of the strongest features.

Create a button:

WHY THIS SUPPLIER?

When clicked, show:

MIZAN Recommendation Reasoning

Technical
✓ Strengths

Commercial
✓ / ⚠ Price position

HSE
✓ Strengths

ICV
🇦🇪 Contribution

Risk
✓ / ⚠ Findings

Then:

Evidence Trail

RFP Source
Supplier Source
Criterion
Score
Reasoning

Every important claim should be traceable.

==================================================
25. MIZAN EVIDENCE TRAIL
==================================================

Create a dedicated evidence experience.

Show:

RFP Requirement
↓
Retrieved Evidence
↓
Supplier Evidence
↓
Evaluation Criterion
↓
Score
↓
Risk Assessment
↓
Recommendation

Allow users to click a score and inspect its source.

Example:

Technical Score: 35.2 /40

Source:
RFP — Technical Evaluation

Supplier Evidence:
Supplier Technical Proposal — Page X

This directly supports knowledge grounding and explainability.

==================================================
26. AGENT ACTIVITY
==================================================

Create an Agent Activity page showing actual agent communication.

Example:

10:42:31
🔎 Evidence Agent

Retrieved relevant tender evidence

↓

10:42:34
✓ Compliance Agent

Mandatory screening completed

↓

10:42:39
🔧 Technical Agent

Technical evaluation completed

↓

10:42:42
💰 Commercial Agent

Commercial evaluation completed

↓

10:42:45
🦺 HSE Agent

HSE evaluation completed

↓

10:42:47
🇦🇪 ICV Agent

ICV evaluation completed

↓

10:42:49
⚠ Risk Agent

Risk assessment completed

↓

10:42:52
📝 Recommendation Agent

Supplier ranking generated

When an agent is clicked, show:

INPUT
What it received

TOOL
What tool it used

OUTPUT
What it passed downstream

This must reflect actual execution rather than fabricated logs.

==================================================
27. RISK & HUMAN REVIEW PAGE
==================================================

Create:

MIZAN
Risk & Human Review

Show cases:

✓ Low Risk
⚠ Medium Risk
🚨 Human Review Required

For serious cases:

🚨 HUMAN REVIEW REQUIRED

AI recommendation paused.

Show:

Supplier
Tender
Issue
Evidence
Affected Criterion
Recommended Human Action

Buttons:

REVIEW EVIDENCE
ASSIGN
CONTINUE AFTER REVIEW

==================================================
28. PROCUREMENT REPORT
==================================================

Create a professional report interface.

Header:

ADNOC

MIZAN

PROCUREMENT INTELLIGENCE

Supplier Bid Evaluation Report

Tender:
ADNOC-LCIG/RFP/2026-0412

Sections:

Executive Summary
Tender Information
Supplier Overview
Mandatory Compliance
Technical Evaluation
Commercial Evaluation
HSE Evaluation
ICV Evaluation
Risk Analysis
Supplier Ranking
AI Recommendation
Trade-Off Analysis
Evidence Trail
Human Review

Button:

GENERATE REPORT

The report should look like a real procurement document, not a chatbot response.

==================================================
29. VISUAL SCORE DESIGN
==================================================

Use clean score cards.

For example:

TECHNICAL
35.2 / 40

COMMERCIAL
26.4 / 30

HSE
13 / 15

ICV
14.1 / 15

TOTAL

88.7 / 100

Use proportional visual bars or rings carefully.

Do not overload the page with charts.

The numbers must come from the actual evaluation.

==================================================
30. ROBUSTNESS
==================================================

Handle:

- Unknown suppliers
- Missing documents
- Incomplete bids
- Conflicting evidence
- Missing ICV
- Missing HSE data
- Missing commercial price
- Out-of-scope questions
- Calculation errors

Never crash.

Never hallucinate.

For unsupported dataset questions:

"Not found in the provided challenge dataset. I cannot verify this information."

For unrelated questions:

"MIZAN is designed for ADNOC upstream procurement and supplier bid evaluation."

Same input + same underlying dataset should produce a consistent result.

==================================================
31. AUTOMATED GRADER REQUIREMENTS
==================================================

The implementation must support:

TEST 1:
A question answerable only from the provided dataset returns the correct fact and source.

TEST 2:
A request requiring a tool causes the appropriate registered tool to execute.

TEST 3:
A serious/urgent input triggers human escalation.

TEST 4:
An ordinary input does not trigger escalation.

The system must run against the FULL provided dataset.

Do not hardcode one demonstration example.

==================================================
32. RESPONSIVE DESIGN
==================================================

The application should work on:

Desktop
Laptop
Tablet

Prioritize desktop because the primary user is a procurement engineer.

Maintain readable tables and dashboards.

Do not sacrifice functionality for mobile styling.

==================================================
33. FINAL USER JOURNEY
==================================================

The ideal experience is:

1. User opens MIZAN.
2. ADNOC logo appears and smoothly fades.
3. MIZAN Procurement Intelligence appears.
4. Dashboard loads.
5. Procurement engineer selects the active tender.
6. User clicks START AI EVALUATION.
7. Evidence Agent retrieves information.
8. Compliance Agent checks mandatory requirements.
9. Technical, Commercial, HSE and ICV agents evaluate suppliers.
10. Risk Agent reviews the combined results.
11. Serious cases trigger human escalation.
12. Recommendation Agent ranks eligible suppliers.
13. User sees the supplier comparison.
14. User clicks WHY THIS SUPPLIER?
15. MIZAN shows the reasoning and evidence.
16. User can inspect every important source.
17. User views ICV impact.
18. User reviews risks.
19. User generates the procurement report.
20. Human procurement engineer makes the final decision.

==================================================
34. FINAL DESIGN PHILOSOPHY
==================================================

MIZAN should feel like:

A professional ADNOC procurement environment enhanced by intelligent automation.

NOT:

A generic AI chatbot.

NOT:

A futuristic AI experiment.

NOT:

A dark cybersecurity dashboard.

The visual and functional identity should communicate:

BALANCE
EVIDENCE
TRANSPARENCY
PRECISION
RISK AWARENESS
HUMAN CONTROL

The first impression should be:

" This looks like something a real procurement engineer could use."

The core message should be:

MIZAN helps procurement engineers evaluate supplier bids across Technical, Commercial, HSE and ICV criteria, identify risk, trace conclusions back to evidence, and produce a defensible recommendation for human review.

Prioritize working backend functionality and genuine agent communication first, then polish the UI around the working system.
