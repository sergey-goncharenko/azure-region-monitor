---
models:
  providers:
    github-copilot:
      models:
        gpt-6-astra:
          cost:
            input: "0.000025"
            output: "0.000075"
            cache_read: "0.000002"
            cache_write: "0.000025"
---
<!--
Model-specific Azure BYOK accounting, not model selection or automatic failover.
Verified 2026-09-26 against https://prices.azure.com/api/retail/prices:
armRegionName=eastus2, skuName contains '6-astra' and 'Std Gl', currencyCode=USD.
USD per million tokens (input/output/cache-read/cache-write):
short context = 10/50/1/12.5; long context = 20/75/2/25.
Use the long-context rates for every Astra request, with input raised to the
$25/M cache-write ceiling (not the $20/M ordinary-input tariff). Values above are
USD PER TOKEN (AWF provider overlays multiply by 1,000,000). Do not replace this
with default-ai-credits-pricing: unrecognized, unpriced models must fail closed.
The copilot provider accepts github-copilot pricing even for Azure BYOK.
AWF v0.28.10 accounts for token classes that its usage parser actually receives;
the cache-write rate does not manufacture missing Azure Responses usage data.
Its response.completed SSE parser does not extract cache-write tokens separately:
https://github.com/github/gh-aw-firewall/blob/v0.28.10/containers/api-proxy/token-parsers.js
Specifically, usage.input_tokens_details.cache_write_tokens is ignored. Responses
input_tokens includes cache-read and cache-write subsets; AWF subtracts cached
reads but leaves unrecognized writes in ordinary input. Pricing that remainder
at $25/M bounds both fresh input ($20/M) and writes ($25/M), without pretending
the missing write breakdown is zero-cost. Retain cache_write=$25/M for separately
recognized writes. With I total input, R cached reads, W cache writes, O output:
bound = 25*(I-R) + 2*R + 75*O; long tariff = 20*(I-R-W) + 25*W + 2*R + 75*O,
both divided by 1,000,000. The excess is 5*(I-R-W)/1,000,000, never negative
when R/W are disjoint subsets of I. Short-context tariffs are lower still.
These are conservative rates, not a hard pre-request reservation or invoice
reconciliation. Missing usage and in-flight spend still require canary review.
-->
