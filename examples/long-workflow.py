# Trusted UI validation fixture: eight observable Steps, no model calls.
s1 = input_df.dropna(subset=['region'])
s2 = s1.fillna({'quantity': 0})
s3 = s2.drop_duplicates(subset=['order_id'])
s4 = s3.assign(amount=s3['quantity'] * s3['price'])
s5 = s4.rename(columns={'region': 'area'})
s6 = s5.sort_values(['amount'], ascending=False, kind='stable')
s7 = s6.groupby(['area'], as_index=False, dropna=False).agg(total=('amount', 'sum'))
result = s7.sort_values(['total'], ascending=False, kind='stable')
