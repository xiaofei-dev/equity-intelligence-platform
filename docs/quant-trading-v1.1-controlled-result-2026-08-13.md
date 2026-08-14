# Quant Trading v1.1 Controlled Development Result

## Decision

`QUANT-V11-CONTROLLED-20260812-008` completed its single authorized FULL191
development execution and exact replay. The frozen interpretation is
`NOT_DIRECTIONALLY_SUPPORTIVE_NO_RETUNING_ON_SAME_OUTCOME`. Five of nine
numeric gates passed and four failed. The model remains `NOT_VALIDATED`, and
this result does not authorize parameter changes against the same observed
outcome.

This is a current-survivor, development-only retrospective. It is neither an
untouched holdout nor evidence of future returns. The result does not authorize
brokerage execution, portfolio weights, deployment, or an evidence-label
upgrade.

## Immutable execution evidence

The journal contains exactly six events: preparation intent, structural
completion, outcome-access intent, execution intent, post-access
pre-performance input seal, and completed terminal. The post-access seal hash
is `2FF0AD54AEC0969C58C89EE2953E52900769A4F219D75864115EAE9E998B26FA`.
The completed terminal hash is
`05DBD974B1B9BC9350586BF37435926AF80D467947BE1A34311217B7FB7B2348`.
The exact event artifact, event, and file hashes are bound in the Git-safe
[aggregate result](../contracts/quant-trading-v1.1/historical-execution-v1.1.8-controlled-result.json).

The four immutable result-file hashes are:

- Primary C9 cost replay: `4677B7B0B557D9C8991D2A8A1B98F099EC8F0523A1CEFF347CACB31F02FF7A61`.
- Fixed-five-bps sensitivity: `8E9D319E88C1FC6AB10643829D656E3286E792CD013728C3BB798AEC67E37261`.
- SPY benchmark: `1AF8B2E463988AE7CD97ADEC9AC8D8CDADD9C23718BCF3B9BD23012C52D56830`.
- Complete terminal registry: `F697EF5EE1366B198AFC1A55F4B6D6B50FCB6EB64A0BECAEBBB9639CBA995035`.

The aggregate fixture contains no raw payload, daily NAV row, order, security
row, licensed value, provider response, or private storage path.

## Observed development metrics

The common portfolio window is 2015-01-05 through 2026-07-27, covering 2,906
completed portfolio sessions. Starting from USD 100,000:

| Replay | Final NAV | CAGR | Maximum drawdown | Zero-rate Sharpe |
|---|---:|---:|---:|---:|
| Primary C9 cost | 237,071.67 | 7.76% | -14.33% | 0.770 |
| Fixed five bps | 231,463.75 | 7.53% | -15.62% | 0.721 |
| SPY | 437,644.04 | 13.63% | -33.69% | 0.816 |

The primary replay completed 1,348 closed trades and 2,696 filled orders. Its
transaction cost was USD 3,054.46, time in market was 77.80%, and severe-loss
rate was zero under the frozen definition. These are historical observations,
not forecasts.

## Frozen gate result

The passing gates were completed sessions, closed trades, drawdown
deterioration, severe-loss rate, and the fixed-five-bps final-NAV sensitivity.
The failing gates were:

- `minimumCagrMinusSpy`: primary CAGR lagged SPY by about 5.87 percentage
  points annually.
- `minimumTotalReturnMinusSpyExclusive`: primary total return lagged SPY by
  about 200.57 percentage points over the full window.
- `minimumSharpeAdvantageVsSpy`: primary Sharpe lagged SPY by about 0.046 and
  did not reach the required positive 0.10 advantage.
- `minimumPositiveSpyCagrExcessSubperiods`: zero of three observed subperiods
  beat SPY on CAGR; the frozen minimum was two.

The exact gate-set hash is
`sha256:4f0b7581771aae42e4b3dd6917ad7cddec166f9415221a200431fcf0b9ddb186`.
The exact acceptance-content hash is
`sha256:d58c649c4251ee05709a5ce9d0ff5af7c6b68440e497a77be7d6f3fd6263f25b`.

## Closeout

The run is complete and immutable. It must not be rerun or reinterpreted as a
passing result. Any redesigned strategy requires a separately versioned
economic thesis, newly preregistered protocol, and a new outcome boundary. The
existing Quant Trading v1.1 model remains `NOT_VALIDATED`.
