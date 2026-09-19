---
name: check_gmail_emails
title: Summarize Unread Emails in Gmail
description: Opens Gmail, identifies unread messages, and provides a summary of the
  top three unread emails.
domain: productivity
triggers:
- summarize unread emails
- check my inbox
- read top emails
- email summary
parameters:
- name: num_emails
  description: The number of unread emails to summarize.
  type: string
  default_value: 3
  required: false
  choices: []
- name: sender_filter
  description: Optional filter to limit search to a specific sender (e.g., "boss",
    "support").
  type: string
  default_value: all
  required: false
  choices: []
author: intelligent_synthesis
version: 1.0.0
tags:
- email
- gmail
- productivity
- reading
- summary
---

# Summarize Unread Emails in Gmail

Opens Gmail, identifies unread messages, and provides a summary of the top three unread emails.

## Cognitive Strategy & Workflow
1.  **Launch Application:** Navigate to the desktop or browser environment to locate the Gmail application icon or window. If not open, open the Gmail web interface.
2.  **Verify Unread State:** Confirm the presence of unread messages by checking the red dot indicator on the inbox icon or the "Unread" label in the sidebar.
3.  **Filter (Optional):** If the `sender_filter` parameter is provided, visually locate the search bar and input the filter term. Ensure the results update to reflect the filtered list.
4.  **Identify Target Emails:** Scan the email list for the top {num_emails} entries marked as unread. Prioritize based on recency or importance indicators (e.g., "Important" flag).
5.  **Extract Content:** For each selected email, read the subject line and the preview text. If the preview is insufficient, click the email to open the full view and read the body content.
6.  **Synthesize Summary:** Generate a concise text summary combining the subjects
