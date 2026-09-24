# KALE — Football Live Value Engine

Gerçek maçlar, gerçek kapanış oranları, **kendi** Dixon-Coles + Elo + form motoru.

Goaldir / GOAL API **sadece veri** için: bülten, oran, kadro, canlı skor, sonuç.
Goaldir’in hazır `/predictions` sayfası **çağrılmaz ve karıştırılmaz**.

Canlı bahis adapter’ı kapalı (`ENABLE_LIVE_EXECUTION=false`). Paper ledger önce.

## GitHub Secrets (eksikler)

Zorunlu değil ama bülten + oran + kadro için **bunu ekle**:

| Secret | Ne işe yarar |
|---|---|
| `GOALDIR_API_KEY` | Goaldir/GOAL API. `Authorization: Bearer …` |
| `GOAL_API_KEY` | Aynı anahtarın alias’ı |

İsteğe bağlı:

| Secret | Ne işe yarar |
|---|---|
| `API_FOOTBALL_KEY` | api-football.com yedeği |
| `ODDS_API_IO_KEY` | ekstra oran feed’i |

Anahtar yoksa motor durmaz: football-data.co.uk tarihi + ESPN bülteni ile **gerçek** maç tahmin eder.

## Ne çekilir, ne çekilmez

Günde 2–4 capture (Actions cron). Goaldir’e spam yok:

- `GET /fixtures/date/{today}` + `{tomorrow}` (TTL 3s)
- `GET /results/yesterday`
- `GET /fixtures/live` **bir kez**
- Oran/kadro: yalnızca **8 saat içindeki** maçlar, run başına en fazla 18 extra GET
- `/predictions` **yasak**

Cache SQLite `http_cache` tablosunda. Aynı URL TTL içinde tekrar gitmez.

## Pipeline

```
football-data.co.uk history
        → ratings (Dixon-Coles attack/defense + Elo)
        → Goaldir/ESPN bulletin
        → predict (1X2, Üst/Alt 2.5, KG)
        → value vs market (de-vig, edge, EV)
        → paper kupon
        → settle from real scores
        → live remaining-time Poisson
```

Kenar süzgeci (yüksek isabet için pas geçer): `odds ∈ [1.38, 3.8]`, `p ≥ 0.46`, `edge ≥ 0.04`.

## Çalıştırma

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # GOALDIR_API_KEY=
python -m src.engine.cli init
python -m src.engine.cli ingest
python -m src.engine.cli capture
python -m src.engine.cli backtest
python -m src.engine.cli live
python -m src.engine.cli settle
```

Raporlar: `data/reports/latest.json`, `picks.json`, `live.json`, `settlement.json`.

## Ligler

40 yarışma: big-5 + 2. ligler, Süper Lig, Eredivisie, Primeira, Belçika, İskoçya, Yunanistan, İskandinav, MLS, Liga MX, Brasileirão, Arjantin, J1, SPL, UCL/UEL/UECL. Liste: `config/leagues.json`.

## Canlı bahis

`execution/betfair.py` bilinçli olarak `NotImplementedError`. Paper ROI ve kalibrasyon oturmadan açma.
