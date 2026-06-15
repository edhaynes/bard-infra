# Contract — fabric name resolution (INFRA-1)

**Status:** Frozen, 2026-06-15. Changes go through a new commit, not a silent
edit (per the API/contract-first rule, `coding-rules.md §11`).

The MVP backend is **MagicDNS-only** (Eddie, 2026-06-15): every fabric endpoint
is addressed by a stable **logical name** that the OS resolver (Tailscale
MagicDNS) maps to a current address. Names survive IP churn; raw IPs do not.
Self-hosted DNS (INFRA-2) is the post-MVP successor; this contract is written to
outlive the backend swap — only the `Resolver` implementation changes.

## Rules

1. **Fabric endpoints are addressed by logical name, never a raw IP.** A
   configuration value that names a fabric participant (Router, Registry, an
   agent, the broker front door) MUST be a resolvable name, optionally with a
   `:port` suffix. A raw IPv4 or IPv6 literal in that position is a
   **configuration error**, rejected at startup.
2. **Resolution is fail-fast.** If a logical name does not resolve at startup,
   the process MUST crash with a clear, named error (`coding-rules.md §0.11`) —
   never limp along with an unresolved endpoint.
3. **The resolver is a swappable backend** (`coding-rules.md §3`). The default
   is the OS resolver (`socket.getaddrinfo`, which MagicDNS serves). A
   registry-backed or self-hosted-DNS resolver (INFRA-2) substitutes behind the
   same interface with no caller change.
4. **Resolution is by name on every use, not pinned once.** A node whose
   address changes (reimage, DHCP, tailnet reassignment) MUST remain reachable
   by the same name with **no config edit** — the INFRA-1 done-signal.

## Interface (frozen)

```
class Resolver(ABC):
    def resolve(self, host: str) -> list[str]: ...
    # Returns one or more current addresses for `host`.
    # Raises NameResolutionError if the name does not resolve.

def validate_endpoint(value: str, resolver: Resolver) -> EndpointResolution
    # value: "name" or "name:port".
    # Rejects empty input            -> ValueError
    # Rejects a raw IP literal host  -> RawIPError
    # Rejects an unresolvable name   -> NameResolutionError
    # Returns the parsed name, optional port, and current addresses.
```

`EndpointResolution` carries `name`, `port` (or `None`), and `addresses` (the
current resolution — informational; callers keep addressing by `name`).

## Done-signal (tested)

A test swaps a node's address behind a fixed name and asserts `validate_endpoint`
still accepts it and returns the **new** address — proving name-based access
survives IP churn. 100% line + branch coverage on the validator and resolver
(`--cov-branch --cov-fail-under=100`).
