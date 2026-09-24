name: KALE capture
on:
  workflow_dispatch:
    inputs:
      mode:
        description: "capture | live | settle"
        default: capture
        required: false
  schedule:
    - cron: "10 6 * * *"
    - cron: "10 11 * * *"
    - cron: "10 15 * * *"
    - cron: "40 19 * * *"
jobs:
  pipeline:
    runs-on: ubuntu-latest
    timeout-minutes: 25
    permissions:
      contents: read
    env:
      GOALDIR_API_KEY: ${{ secrets.GOALDIR_API_KEY }}
      GOAL_API_KEY: ${{ secrets.GOAL_API_KEY }}
      API_FOOTBALL_KEY: ${{ secrets.API_FOOTBALL_KEY }}
      ODDS_API_IO_KEY: ${{ secrets.ODDS_API_IO_KEY }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - uses: actions/cache@v4
        with:
          path: |
            data/raw
            data/processed
            data/models
          key: kale-hist-${{ hashFiles('config/leagues.json') }}
          restore-keys: kale-hist-
      - run: pip install -r requirements.txt
      - name: Init + ingest
        run: |
          python -m src.engine.cli init
          python -m src.engine.cli ingest
      - name: Train morning or manual
        if: github.event.schedule == '10 6 * * *' || github.event_name == 'workflow_dispatch'
        run: python -m src.engine.cli train
        continue-on-error: true
      - name: Capture bulletin
        run: python -m src.engine.cli capture
      - name: Settle
        run: python -m src.engine.cli settle
        continue-on-error: true
      - name: Live scan
        if: github.event.schedule == '10 15 * * *' || github.event.schedule == '40 19 * * *' || github.event.inputs.mode == 'live'
        run: python -m src.engine.cli live
        continue-on-error: true
      - uses: actions/upload-artifact@v4
        with:
          name: kale-reports-${{ github.run_id }}
          path: data/reports/
          if-no-files-found: warn
