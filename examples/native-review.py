def scale(df):
    out = df.copy()
    out['total'] = out['x'].apply(lambda v: v*2)
    return out
s1 = scale(input_df)
s2 = s1.loc[s1['x'] >= 2].copy()
result = s2[['total']].copy()