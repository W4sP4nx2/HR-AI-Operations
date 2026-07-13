# Three Naive Baseline Models

These baselines establish cheap, inspectable performance floors for three real
product paths. They are not interchangeable with production validation and none
may make an automated adverse employment decision.

## Resource contract

The baseline module imports no Torch/Triton library, makes no network request,
downloads no artifact, and trains no model. The full golden evaluation contains
30 small records and runs with:

```bash
cd backend
python -m scripts.evaluate_baselines
```

The existing attrition RandomForest is limited to `n_jobs=1`; importing the API
must not claim every CPU core. GPU kernels and their tests remain separate.

## Why these baselines

Simple text classifiers can remain competitive while being dramatically cheaper
than deep architectures, making them useful evaluation floors
([Joulin et al., 2016](https://arxiv.org/abs/1607.01759)). Sentence embeddings
are appropriate when semantic similarity must go beyond lexical overlap
([Reimers and Gurevych, 2019](https://arxiv.org/abs/1908.10084)), but the lexical
floor remains valuable because its errors are easy to inspect.

HR decisions are high stakes. Prefer inherently inspectable models where their
quality is adequate instead of attaching explanations to opaque behavior
([Rudin, 2018](https://arxiv.org/abs/1811.10154)). A probability-like score must
also be evaluated for calibration, not accuracy alone
([Guo et al., 2017](https://arxiv.org/abs/1706.04599)). Finally, every future
real dataset needs documented motivation, composition, collection, and intended
use following the datasheet discipline
([Gebru et al., 2018](https://arxiv.org/abs/1803.09010)).

## Baseline 1: keyword triage

**Product role:** zero-key fallback for routing HR tickets.

**Implementation:** `KeywordTriageBaseline` gives URGENT terms absolute priority,
then selects the category with the most matching terms. No match defaults to
POLICY with an explicit low-confidence rationale.

**Golden result:** 14 tickets, macro-F1 `0.9333`, URGENT recall `1.0`. The known
miss is “My paycheck is missing this month,” which defaults to POLICY because
the vocabulary lacks payroll terms.

**Keep when:** URGENT recall remains `1.0` and macro-F1 is at least `0.80` on a
reviewed, versioned ticket set.

**Discard or narrow when:** ambiguous language, multilingual tickets, or domain
drift lowers URGENT recall. Never silently expand keywords from production text;
review changes because a new URGENT stem can over-route unrelated cases.

## Baseline 2: resume skill overlap

**Product role:** auditable 40% component of the resume score and a diagnostic
floor for semantic retrieval.

**Implementation:** `SkillOverlapBaseline` computes matched required skills over
all required skills, with conservative prefix matching for plurals/stems.

**Golden result:** six pairs, average precision is reported by the local harness. The deliberate negation
trap (“never used Python or LangGraph”) scores `1.0`, proving lexical presence
does not establish demonstrated experience.

**Keep when:** AP is at least `0.70` and output remains advisory. It is useful for
showing recruiters exactly which terms affected coverage.

**Discard as a decision rule:** always. It may contribute to ranking but must not
auto-reject. The existing skill-validation pass and human review are load-bearing,
not optional decoration.

## Baseline 3: attrition rule score

**Product role:** transparent fallback if scikit-learn is absent and a comparison
floor for any trained attrition model.

**Implementation:** `AttritionRuleBaseline` normalizes the six approved
job-related inputs plus the existing promotion/manager disengagement interaction,
then returns a weighted score and sorted contributions. It uses no protected
attribute or free text.

**Golden result:** ten deliberately clear smoke profiles, balanced accuracy
`1.0`, positive recall `1.0`, Brier score `0.0358`.

**Important limitation:** these hand-authored extremes are not a representative
employee dataset. The result proves arithmetic and ordering only. It says nothing
about real attrition accuracy, fairness, causal validity, or calibration.

**Keep when:** scikit-learn is unavailable or as an offline comparison floor.

**Discard for deployment:** until a governed, representative dataset beats a
pre-registered baseline on average precision, Brier score, subgroup error rates,
and temporal holdout performance. Even then, output remains advisory and starts
a retention conversation only.

## Evaluation and promotion policy

| Baseline | Primary metrics | Current gate | Product status |
|---|---|---:|---|
| Keyword triage | Macro-F1, URGENT recall | `>=0.80`, `=1.0` | Served fallback |
| Skill overlap | Average precision + named negation guard | `>=0.70` | Score component only |
| Attrition rules | Balanced accuracy, Brier | `>=0.80`, `<=0.20` | Resilience/evaluation floor |

Golden gates are regression checks, not research claims. Before promotion:

1. Freeze a versioned evaluation dataset that was not used to write the rules.
2. Report class prevalence and precision-recall metrics for imbalanced outcomes.
3. Add temporal holdout evaluation for attrition to avoid future-data leakage.
4. Audit subgroup errors using protected fields held outside model inputs.
5. Reject a candidate model that wins only on training accuracy or unexplained
   synthetic data.

## Authoritative implementation

- Baselines: `backend/models/naive_baselines.py`
- Golden data and metrics: `backend/models/baseline_evaluation.py`
- CLI report: `backend/scripts/evaluate_baselines.py`
- Regression tests: `backend/tests/test_naive_baselines.py`
