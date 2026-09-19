---
name: twitter_bookmarks
title: Check Twitter Bookmarks
description: Opens the Twitter application and navigates to the Bookmarks section
  to review saved tweets.
domain: productivity
triggers:
- check twitter bookmarks
- read my saved tweets
- view bookmarked posts
- show twitter bookmarks
parameters:
- name: query_None
  description: Optional natural language filter (e.g., "show posts about coding")
  type: string
  default_value: ''
  required: false
  choices: []
author: intelligent_synthesis
version: 1.0.0
tags:
- social-media
- productivity
- twitter
- bookmarks
---

# Check Twitter Bookmarks

Opens the Twitter application and navigates to the Bookmarks section to review saved tweets.

## Cognitive Strategy & Workflow
1.  **Identify Application Context**: Locate the Twitter application window. If multiple instances exist, prioritize the one with the most recent activity or the one matching the user's active focus area.
2.  **Locate Navigation Controls**: Find the primary navigation bar (usually at the top) containing the "Home", "Explore", "Bookmarks", and "Profile" icons.
3.  **Execute Navigation**: Click the "Bookmarks" icon. If the user provided a specific `{query}` parameter, look for a search bar within the Bookmarks view and input the text.
4.  **Verify Content**: Ensure the feed displays a list of tweets. If the list is empty or the user specified a filter, re-evaluate the search criteria.
5.  **Report Status**: If the user asked for a summary, read the top 3-5 most recent tweets and summarize the key topics.

## Visual Landmarks & Grounding Cues
*   **Application Window**: A window with a recognizable Twitter logo (blue bird) in the top-left corner.
*   **Navigation Bar**: A horizontal
