"""The two active presentations. Legacy IDs are read/import aliases only."""
VARIANTS={'ex':'ex-situ-review-v2','in-situ':'in-situ-review-v2'}
ALIASES={'A':'ex','B2':'ex','B':'in-situ','C':'in-situ'}


def normalize(value):
    value=ALIASES.get(value,value)
    if value not in VARIANTS:raise ValueError('조건은 ex 또는 in-situ여야 합니다.')
    return value
