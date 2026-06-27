# Reference Reviews

Phase 0 writes one review file per cloned reference repository.

Required format:

```text
license
files inspected
patterns to replicate
patterns to avoid
security/dependency concerns
native implementation decision
```

Reference repos are read-only design inputs. They are not execution authority and must not be imported by production code unless license, security, attribution, and tests approve that specific use.
