# Background execution on one Windows PC

OmniVLA can do a meaningful share of work without taking over the user's mouse or foreground window, but Windows does not provide one universal background-input mechanism for every desktop application. The reliable design is hybrid.

## Recommended execution ladder

1. **Web applications:** use a headless Playwright or Edge WebDriver session. This is fully background-capable and does not depend on the user's foreground browser tab.
2. **Accessible desktop controls:** use Microsoft UI Automation patterns for inspection, value entry, selection, invocation, and waiting. These operations target a control rather than global mouse coordinates and can work while another window is foregrounded.
3. **Window capture:** use Windows Graphics Capture for an occluded target window when supported. This gives the visual model evidence without exposing or moving the window.
4. **Visual fallback:** use the current screenshot-and-pointer executor only when an application does not expose a usable semantic control pattern. `SendInput` necessarily targets the interactive foreground desktop, so the UI must clearly indicate that the user should avoid simultaneous input for this part of a run.
5. **Isolated workspace (optional):** Windows Sandbox can provide a separate interactive environment with vGPU, mapped folders, startup commands, and a memory cap. This avoids interference with host applications, but it is ephemeral and unavailable on Windows Home.

## Practical implementation path

- Add a capability probe per action target rather than a global “background” promise.
- Route browser goals to a persistent local headless browser context.
- Route desktop actions through UI Automation `Invoke`, `Value`, `Selection`, and `Scroll` patterns when available.
- Keep the visual model as the planner and verifier: semantic tools are additional precise actions, not macros or a replacement for reasoning.
- Surface one simple state to the user: **Background**, **Needs foreground**, or **Isolated workspace**. Do not expose transport names in the normal task UI.
- Re-observe after every semantic action and fall back to visible control only when verification fails or the target has no compatible pattern.

Microsoft's WinApp CLI is a promising adapter for this design. Its UI automation commands use UI Automation patterns for semantic actions, and its capture path can use Windows Graphics Capture for occluded windows. As of this review it remains a public-preview dependency, so OmniVLA should integrate it behind a capability boundary rather than make it mandatory.

## Sources

- [Microsoft UI Automation overview](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-uiautomationoverview)
- [Microsoft UI Automation for automated testing](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-usefortesting)
- [Microsoft WinApp CLI UI automation](https://learn.microsoft.com/en-us/windows/apps/dev-tools/winapp-cli/ui-automation)
- [Microsoft WinApp CLI repository and releases](https://github.com/microsoft/winappcli)
- [Playwright browser and headless operation](https://playwright.dev/docs/browsers)
- [Microsoft Edge WebDriver](https://learn.microsoft.com/en-us/microsoft-edge/webdriver/)
- [Windows Sandbox configuration](https://learn.microsoft.com/en-us/windows/security/application-security/application-isolation/windows-sandbox/windows-sandbox-configure-using-wsb-file)
- [Windows Sandbox overview and edition requirements](https://learn.microsoft.com/en-us/windows/security/application-security/application-isolation/windows-sandbox/)
