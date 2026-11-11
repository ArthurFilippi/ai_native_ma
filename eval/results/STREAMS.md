# Stream ablation

Mock provider, retrieval only, system A5, seeds 1234, 1, 2, 3, 4, test split. Questions pooled over the seeds; 95 percent percentile intervals of a paired bootstrap (2000 resamples). Synthetic data: read the differences, not the levels. Questions: {"fact_base": 682, "fact_mixed_off": 682, "fact_mixed_on": 682, "market_off": 152, "market_on": 152}.

| Comparison | nDCG@10 A | nDCG@10 B | Difference | Recall@10 difference |
|---|---|---|---|---|
| news mixed in, fact questions (weights off vs no news) | 0.955 [0.948, 0.962] | 0.954 [0.947, 0.961] | 0.001 [-0.001, 0.003] | -0.000 [-0.001, 0.000] |
| fact questions with news, stream weights on vs off | 0.941 [0.933, 0.950] | 0.955 [0.948, 0.962] | -0.014 [-0.020, -0.008] | -0.000 [-0.001, 0.000] |
| market questions, stream weights on vs off | 0.590 [0.524, 0.658] | 0.589 [0.522, 0.657] | 0.001 [0.000, 0.003] | 0.002 [0.000, 0.005] |
