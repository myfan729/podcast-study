# Podcast Study — app (Expo)

Real English podcasts with a synced transcript, sentence-by-sentence Korean, words & expressions and a review deck.

## Run
1. `npm install`
2. Put the Supabase **Project URL** and **anon key** in `app.json → expo.extra` (`supabaseUrl`, `supabaseAnonKey`)
   or as `EXPO_PUBLIC_SUPABASE_URL` / `EXPO_PUBLIC_SUPABASE_ANON_KEY`.
3. `npx expo start` → open in Expo Go (audio works; background playback needs a build).
4. Test builds on a phone: `npx eas-cli@latest build --profile preview -p android` (APK) /
   `-p ios` (TestFlight needs an Apple developer account).

## How it fits together
- **Supabase** (`../supabase/migrations`): shows, episodes, subscriptions, unlocks (free: 2 episodes / 7 days),
  vocab, entitlements; study packs live in the private bucket `episodes`, readable only for unlocked episodes.
- **Worker** (`../pipeline/app_worker.py`, GitHub Actions `app-worker.yml`): refreshes feeds, builds the
  episodes users open (transcript → sentences → Korean → words/expressions → sync references).
- **Catalog** (`../tools/catalog`): candidates probed and verified end to end, seeded by `app-db.yml`.

## Screens
홈 (followed shows) · 찾기 (catalog) · 쇼 · 에피소드 (script / 단어 및 표현) · 단어장 (SM-2 review) · 설정
