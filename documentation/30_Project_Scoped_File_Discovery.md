# Project-scoped file discovery

The planner now uses an explicitly remembered `project → stored_in → folder`
relationship when the current request matches one project. Only absolute folder
locations are used. Multiple relevant projects do not silently select one.

File search receipts describe the selected scope. Missing remembered folders
return no results without expanding the search. Explicit file locations override
the remembered default and retain exact lookup behavior. Injected planner context
does not additionally consult persistent memory for folder selection.

The filesystem search now respects supplied roots in every discovery branch:
scoped queries bypass the global Everything index, empty scopes return no files,
exact paths outside supplied roots are rejected, and resolved paths are checked
before traversing directories or returning file matches. The walk uses a shared
monotonic deadline across roots and checks it inside large file lists.

Validation: all 301 tests passed. The 31 targeted tests cover discovery, gateway dispatch,
planner sequencing, and personal tools, including new scope integration tests.
These use synthetic local folders and mocked model responses; live model project
selection quality has not been evaluated. Remembered folders are advisory defaults,
not an access-control sandbox. OS calls themselves cannot be interrupted by the
walk deadline, and filesystem changes can still race discovery.
