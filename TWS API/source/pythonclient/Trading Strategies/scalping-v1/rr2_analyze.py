import sys, pandas as pd
f = sys.argv[1] if len(sys.argv) > 1 else "results/rr2_all.csv"
r = pd.read_csv(f)
pd.set_option('display.width', 260); pd.set_option('display.max_colwidth', 95); pd.set_option('display.max_rows', 400)
w = r.pivot_table(index=['cfg', 'params', 'sym'], columns='part', values=['n', 'win', 'pf', 'net', 'tgt_rate']).reset_index()
w.columns = ['_'.join(c).strip('_') for c in w.columns]
w['pos'] = (w.net_IS > 0).astype(int) + (w.net_OOS > 0).astype(int)
g = w.groupby(['cfg', 'params']).agg(pos=('pos', 'sum'), net=('net_ALL', 'sum'), minpf=('pf_ALL', 'min'))
piv = w.pivot_table(index='cfg', columns='sym', values=['pf_ALL', 'win_ALL', 'n_ALL'])
piv.columns = [f'{a[:-4]}_{b}' for a, b in piv.columns]
g = g.join(piv, on='cfg').sort_values(['pos', 'net'], ascending=False)
print(g.round(2).to_string())
