s1 = input_df.loc[(input_df['status'] == '완료') & (input_df['quantity'] > 2)].copy()
s2 = s1.assign(amount=s1['quantity'] * s1['price'])
result = s2.groupby(['region'], as_index=False, dropna=False).agg(total=('amount', 'sum'))