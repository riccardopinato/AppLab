# Bounded code hygiene

During each substantive change, inspect only the touched subsystem for obsolete
implementations, dead code, duplicate workers, unused dependencies, stale flags,
or orphan assets. Remove only items proven superseded and within task scope.
Do not delete migrations, evidence history, compatibility or fallback without
an explicit proof of safety. When a module reaches its registered growth ceiling,
extract a bounded helper instead of raising the budget by default. Re-run
appropriate validation after cleanup.
