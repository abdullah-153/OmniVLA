# Discovery state consistency

Six regression cases reproduced stale or prematurely published discovery state:

- A cached query returned its original text but left another query's matches active.
- Search exceptions, formatting exceptions, invalid arguments, and invalid argument
  objects left earlier matches active.
- A formatting failure still authorized a newly found file for reading.

The gateway now clears the current match list before validating a new search,
stores an independent match snapshot alongside each successful cached result,
and restores that snapshot on cache hits. Search scope is included in cache keys.
Matches and read eligibility are published only after successful discovery and
formatting. Previously successful discoveries remain eligible for explicit reads
within the same request; current matches always describe the current search.

The planner checks search success before automatic reading and distinguishes a
failed search from a completed search with no matches. A regression test performs
one successful discovery followed by a failed discovery and verifies that the
earlier file is not read.

Validation: 44 targeted tests passed across gateway behavior, project discovery,
planner sequences, and personal tools. These checks use temporary files and mocked
model responses. They do not claim protection against all filesystem races or
guarantee model response quality after an error. Cached discovery remains scoped
to one planner request; actual local reads still read fresh bytes.
