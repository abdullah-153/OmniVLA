# Research citations in the console

The console renders Markdown HTTP(S) links and bare HTTP(S) URLs in conversation and plan text as clickable sources. Each link shows its destination host so a short label cannot hide the site it opens. Code spans remain code, and unsupported schemes such as `javascript:` and `file:` remain plain text. The renderer escapes text and URL attributes before inserting the small supported Markdown subset into the page.

The desktop Electron shell still blocks page-initiated windows and navigation. A click on a rendered source uses the preload bridge to ask the main process to open a validated HTTP(S) URL in the system browser. The main process independently checks the scheme, credentials, length, and backslashes. In an ordinary browser or paired web view, the link opens in a new tab with `noopener noreferrer`.

The link is a destination supplied in assistant text, not proof that the source supports the answer. The Electron fixture checks safe, unsafe, bare, and code-form URLs in rendered messages. The Node test checks the main-process URL validator. A live external-browser launch is intentionally not part of the automated smoke flow.
