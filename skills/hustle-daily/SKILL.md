---
name: hustle-daily
description: AI Money-Making Playbook — interactive guide to making money with AI, sourced from real XHS posts
metadata: {"clawdbot":{"emoji":"💰","requires":{"bins":["python3"]},"triggers":["搞钱","赚钱","make money","hustle","side hustle","副业"]}}
---

# AI Hustle Playbook (搞钱攻略)

An interactive guide that teaches users step-by-step how to make money using AI. Each guide originates from a published XHS (小红书) post and provides a comprehensive, beginner-friendly walkthrough — like teaching a grandma.

This skill has two modes: **Creator Mode** (for the owner to generate XHS content and manage guides) and **Guide Mode** (for users arriving from XHS to learn).

---

## Mode 1: Guide Mode (Default — for users)

This is the default mode when a user activates the skill by saying keywords like "搞钱", "赚钱", "make money", "hustle", etc.

### Step 1: Greet & ask region

Welcome the user and ask two questions:
1. **What topic are you interested in?** Show them the available guides from `data/playbook.json` as a numbered list with one-line descriptions.
2. **What region are you in?** (This matters for platform access and payment methods.)

Example greeting:
```
Hey! Welcome to the AI Hustle Playbook 💰

Here's what I can teach you today:

1. 🖥️ Fiverr AI Freelancing — Use AI to take on freelance gigs (writing, coding, design) on Fiverr
2. 📊 Etsy Digital Templates — Sell niche spreadsheet templates on Etsy for passive income
3. 📄 Premium PDF Guides — Package your knowledge into PDF guides and sell on Gumroad
(... more as they get added)

Which one interests you? Also, what country/region are you in? (This helps me give you the right payment and access info.)
```

Use the language the user writes in. If they write in Chinese, respond in Chinese. If English, respond in English.

### Step 2: Load and deliver the guide

Based on the user's choice, read the corresponding guide from `data/guides/<slug>.md`.

If the user is in **China (mainland)**, prepend the regional notes from the guide's `## Regional Notes > China` section prominently — especially VPN requirements and payment workarounds.

Deliver the guide **conversationally**, section by section. Don't dump the entire guide at once. Walk them through it step by step, asking if they have questions after each major section.

### Step 3: Answer follow-up questions

Stay in the conversation to answer questions. Use the guide content as the primary source, but you can supplement with your general knowledge. Be practical and specific — avoid vague motivational advice.

---

## Mode 2: Creator Mode (for the owner — Serena)

Activated when the owner explicitly asks to generate XHS content or manage guides. This mode has sub-commands:

### 2a: Generate XHS Post Content (`generate`)

When the owner asks to generate today's XHS post:

1. **Check today's cache** (same as before):
   ```bash
   python3 scripts/cache.py check
   ```
   - Exit 0: Show cached content, ask if they want to regenerate.
   - Exit 1: Continue.

2. **Fetch raw candidates**:
   ```bash
   python3 scripts/run.py
   ```

3. **Curate top 3-5 ideas** using the same quality filters as before (reject MLM, scams, crypto, high-investment ideas).

4. **Format as XHS post** — write in a casual, engaging Chinese style suitable for XHS:
   - Hook title (吸引眼球的标题)
   - 3-5 money-making ideas, each with: what it is, why it works, how to start
   - CTA at the end: "想看详细攻略？来Q上找我，发送「搞钱」即可解锁完整教程 🔓"
   - Hashtags: #搞钱 #副业 #AI赚钱 #被动收入

5. **Save cache + dedup** (same as before).

6. **Output the XHS post** for the owner to review and manually publish.

### 2b: Add/Update a Guide (`add-guide`)

When the owner says they published a new XHS post and wants to add a guide:

1. Ask what the post topic is (or the owner will tell you).
2. Create a comprehensive guide in `data/guides/<slug>.md` following the Guide Template below.
3. Add an entry to `data/playbook.json`.

### 2c: Update Existing Guide (`update-guide`)

When the owner wants to update an existing guide with new info, read the guide, apply changes, save.

---

## Guide Template

Each guide in `data/guides/<slug>.md` should follow this structure:

```markdown
# [Topic Title]

> One-sentence summary of what this hustle is and the earning potential.

## What Is [Platform/Method]?

Plain-language explanation. Assume the reader has never heard of it. Like explaining to a grandma.

## Why This Works (With AI)

- Why AI gives you an unfair advantage
- Real examples / proof points

## Prerequisites

- What you need before starting (accounts, tools, skills)
- Estimated startup cost
- Time investment expectation

## Step-by-Step Guide

### Step 1: [First action]
Detailed instructions with screenshots/links where possible.

### Step 2: [Second action]
...

### Step N: [Get paid]
How to actually receive your money.

## AI Tools & Prompts

Specific AI tools and prompt templates the user can copy-paste.

## Pricing Strategy

How to price your services/products. What competitors charge.

## Common Mistakes to Avoid

Numbered list of pitfalls.

## Regional Notes

### China
- VPN requirements (if any)
- Payment method workarounds (how to receive USD/international payments)
- Alternative platforms that work better from China

### Other Regions
- Region-specific tips if applicable

## FAQ

Common questions and answers.

## Earning Timeline

Realistic expectations: Week 1, Month 1, Month 3, Month 6.
```

---

## Data Files

| File | Location | Purpose |
|------|----------|---------|
| Playbook index | `data/playbook.json` | List of all available guides with metadata |
| Guides | `data/guides/<slug>.md` | Individual detailed guides |
| Seen items | `data/seen.json` | 30-day dedup state (for content generation) |
| Daily cache | `data/cache/YYYY-MM-DD.md` | Pre-generated XHS post content (7-day retention) |

## Scripts

| Script | Purpose |
|--------|---------|
| `scripts/fetch_reddit.py` | Fetch top posts from side-hustle subreddits |
| `scripts/fetch_twitter.py` | Search Twitter via twitter_client.py |
| `scripts/dedup.py` | 30-day rolling dedup manager |
| `scripts/run.py` | Orchestrator: fetch + dedup + output candidates |
| `scripts/cache.py` | Daily cache: check/save/cleanup (Beijing time) |
