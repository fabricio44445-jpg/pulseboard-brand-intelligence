create table if not exists public.mentions (
  id text primary key,
  brand text not null,
  source text not null,
  publisher text not null,
  title text not null,
  summary text not null default '',
  author text not null default '',
  link text not null,
  published_at timestamptz not null,
  sentiment text not null check (sentiment in ('Positive', 'Neutral', 'Negative')),
  sentiment_score double precision not null default 0,
  collected_at timestamptz not null default now()
);

create index if not exists mentions_brand_published_idx
  on public.mentions (brand, published_at desc);

alter table public.mentions enable row level security;

-- No public policies are created. Pulseboard uses the Supabase service-role
-- key only from server-side Streamlit and GitHub Actions secrets.
