---
name: browser_research
title: Web Research & Synthesis
description: Searches the web for information, extracts key findings from multiple sources, and compiles a structured synthesis.
domain: browser
triggers:
  - "research *"
  - "search web for *"
  - "find information about *"
  - "look up *"
parameters:
  - name: topic
    description: The subject, query, or question to investigate
    type: string
    required: true
  - name: output_app
    description: Target app to record findings (e.g. Notepad, Word, Notion)
    type: string
    default_value: "Notepad"
    required: false
author: system
version: 1.0.0
tags: [web, research, browser, search]
---

# Web Research & Synthesis

Searches the web for information, extracts key findings from multiple sources, and compiles a structured synthesis.

## Cognitive Strategy & Workflow
1. **Focus Browser Window**: Locate and activate Google Chrome or Microsoft Edge. If neither is running, launch via `Win+R` -> `chrome`.
2. **Execute Search**: Click the browser URL/search bar and type search query: `{{topic}}`, then press Enter.
3. **Inspect Search Results**: Look visually for top organic search results, avoiding sponsored ad links.
4. **Extract Content**: Open 1-2 authoritative result pages, extract key factual points and quantitative metrics.
5. **Compile Summary**: Switch to `{{output_app}}`, paste or type the summarized insights in clean bulleted markdown, and save.

## Visual Landmarks & Grounding Cues
- Browser URL Bar: Top center omnibox with magnifying glass or globe icon.
- Organic Search Links: Large blue/purple headline text below search results.
- New Tab Button: '+' icon next to active browser tabs.
- Target App Window: Title bar or taskbar icon matching `{{output_app}}`.

## Failure Modes & Recovery
- **Cookie / GDPR Consent Modal**: If an overlay dialog blocks the page, visually locate the 'Accept', 'Agree', or 'Reject All' button and click it.
- **Cloudflare / Captcha**: If a human challenge is presented, pause execution and request human operator assistance.
- **Page Load Delay**: If page shows a spinning circle or blank screen, wait 2 seconds before retrying navigation.
