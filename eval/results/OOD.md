# Out of distribution check

Provider: mock mock-extractive-v1 (offline mock: rules, not a model). Dataset: `eval/datasets/ood/`, 5 hand written documents, 2 deals, 30 answerable and 6 unanswerable questions. Small sample, no intervals: read the gap with the synthetic test split, not the absolute values. The same author wrote these documents and the system.

| System | Recall@10 | MRR |
|---|---|---|
| A1 | 1.000 | 0.903 |
| A2 | 1.000 | 0.803 |
| A3 | 1.000 | 0.884 |
| A4 | 1.000 | 0.961 |
| A5 | 1.000 | 0.961 |

- Answer accuracy (answerable, value stated in a sourced claim): 0.567
- False abstention (answerable): 0.400
- Correct abstention (unanswerable): 1.000

| Question | What it tests | A5 rank | Abstained | Correct |
|---|---|---|---|---|
| ood01 | revenue asked, net sales and turnover stated | 1 | False | True |
| ood02 | calendar year against FY23 | 1 | False | True |
| ood03 | table column | 1 | False | True |
| ood04 | reported against adjusted | 1 | False | True |
| ood05 | abbreviation adj. | 3 | False | False |
| ood06 | first column | 2 | True | False |
| ood07 | GM% | 1 | False | True |
| ood08 | FTEs | 1 | True | False |
| ood09 | largest against top ten | 1 | False | True |
| ood10 | top ten | 1 | False | True |
| ood11 | order book, dd/mm/yyyy | 1 | False | True |
| ood12 | middle column | 1 | False | True |
| ood13 | capex abbreviation | 1 | False | True |
| ood14 | net financial debt | 1 | False | True |
| ood15 | first column | 1 | False | True |
| ood16 | number in words | 1 | True | False |
| ood17 | footnote | 1 | True | False |
| ood18 | non numeric | 1 | True | False |
| ood19 | twelve months to December 2024 | 1 | False | True |
| ood20 | a year earlier | 1 | True | False |
| ood21 | turnover asked, sales stated | 1 | True | False |
| ood22 | plain year columns | 1 | True | False |
| ood23 | middle column | 1 | True | False |
| ood24 | margin | 1 | False | True |
| ood25 | people | 1 | False | True |
| ood26 | headcount asked, FTE stated | 1 | True | False |
| ood27 | sites called warehouses | 1 | True | False |
| ood28 | capex | 1 | False | True |
| ood29 | five biggest clients | 1 | True | False |
| ood30 | large number | 1 | False | True |
| ood31 | unanswerable | n/a | True | True |
| ood32 | unanswerable, hard | n/a | True | True |
| ood33 | unanswerable | n/a | True | True |
| ood34 | unanswerable, hard | n/a | True | True |
| ood35 | unanswerable | n/a | True | True |
| ood36 | unanswerable | n/a | True | True |
