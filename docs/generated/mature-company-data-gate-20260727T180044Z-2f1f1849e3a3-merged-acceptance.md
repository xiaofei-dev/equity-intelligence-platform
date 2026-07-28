# 100-Security Provider Gate Merged Acceptance

- Aggregate run ID: `20260727T180044Z-2f1f1849e3a3`
- Aggregate JSON SHA-256:
  `5080DA05519C2F03B603BC499698A3298C1225A4BCF4EBFF8A6961697C730475`
- Unique base-universe securities: 120
- Unique live-confirmed PASS securities: 100
- Remaining PARTIAL: 19
- Remaining FAIL: 1
- Aggregate gate status: `PASS`
- Network requests executed by this merge: `false`

This is a cross-run aggregate acceptance. It is not represented as a new
single-run 120-security download.

## Coverage rule

Each base-universe symbol appears exactly once. A later status replaces an
earlier status only when it comes from a hash-verified immutable live report
using the same gate standard. Offline-derived evidence is hash-verified for
lineage but cannot upgrade a security to PASS.

| Source run | Unique PASS used |
|---|---:|
| `20260727T074150Z-50407538afa9` | 71 |
| `20260727T174805Z-516116490045` | 1 |
| `20260727T175355Z-be763adcfa24` | 8 |
| `20260727T175552Z-925cd46d35ff` | 20 |
| **Total** | **100** |

The merged JSON contains symbol, sector, candidate role, source run ID,
source-report SHA-256, latest status, and reason codes for all 120 securities.
No duplicate or non-live PASS record is present.

## Billing evidence

All five contributing live intervals are `PROVISIONALLY_RECONCILED` at run
level. Endpoint-level billing remains `NOT_RECONCILED`.

| Run | Dashboard interval | Delta |
|---|---:|---:|
| `20260727T074150Z-50407538afa9` | 11,512–14,387 | 2,875 |
| `20260727T173753Z-079c976fda3f` | 14,387–14,502 | 115 |
| `20260727T174805Z-516116490045` | 14,502–14,571 | 69 |
| `20260727T175355Z-be763adcfa24` | 14,571–14,778 | 207 |
| `20260727T175552Z-925cd46d35ff` | 14,778–15,238 | 460 |

## Boundary

This acceptance proves the 100-security mature-company provider candidate
threshold. It does not approve Objective Rating execution, the 300–500
point-in-time validation gate, full-market ingestion, or production data
licensing.
