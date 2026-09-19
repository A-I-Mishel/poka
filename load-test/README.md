# Load Testing CI Configuration

## GitHub Actions Workflow

### `.github/workflows/load-test.yml`

```yaml
name: Load Testing

on:
  push:
    branches: [main, release/*]
  pull_request:
    branches: [main]
  schedule:
    - cron: '0 2 * * 0'  # Weekly on Sunday 2 AM
  workflow_dispatch:
    inputs:
      vus:
        description: 'Virtual users'
        required: false
        default: '50'
      duration:
        description: 'Test duration'
        required: false
        default: '5m'
      scenario:
        description: 'Specific scenario to run'
        required: false
        type: choice
        options:
          - all
          - simple_chat
          - deep_mode
          - upload_kb_search
          - upload_download
          - sse_stream
          - kb_search

env:
  BASE_URL: ${{ secrets.PLUTO_LOAD_TEST_URL || 'http://localhost:8000' }}
  K6_PROJECT_ID: ${{ secrets.K6_PROJECT_ID }}

jobs:
  # Quick smoke test on every PR
  smoke-test:
    name: Smoke Test (10 VUs, 30s)
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4

      - name: Set up k6
        uses: grafana/k6-action@v0.2.0

      - name: Run smoke test
        run: |
          k6 run --vus 10 --duration 30s \
            --env BASE_URL=${{ env.BASE_URL }} \
            load-test/k6-scenarios.js
        env:
          BASE_URL: ${{ env.BASE_URL }}

  # Full load test on schedule and main branch
  load-test:
    name: Full Load Test (${{ github.event.inputs.vus || 50 }} VUs, ${{ github.event.inputs.duration || '5m' }})
    runs-on: ubuntu-latest
    timeout-minutes: 30
    if: github.event_name == 'schedule' || github.event_name == 'workflow_dispatch' || github.ref == 'refs/heads/main'
    steps:
      - uses: actions/checkout@v4

      - name: Set up k6
        uses: grafana/k6-action@v0.2.0

      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install -e .

      - name: Start Pluto server (background)
        run: |
          nohup uvicorn backend.main:app --host 0.0.0.0 --port 8000 > server.log 2>&1 &
          sleep 10
          curl -f http://localhost:8000/api/health || (cat server.log && exit 1)

      - name: Run load test
        run: |
          k6 run \
            --vus ${{ github.event.inputs.vus || 50 }} \
            --duration ${{ github.event.inputs.duration || '5m' }} \
            --env BASE_URL=http://localhost:8000 \
            --summary-export=summary.json \
            --out json=results.json \
            load-test/k6-scenarios.js
        env:
          BASE_URL: ${{ env.BASE_URL }}
          K6_PROJECT_ID: ${{ secrets.K6_PROJECT_ID }}

      - name: Check SLOs
        run: |
          python -c "
          import json
          with open('summary.json') as f:
              data = json.load(f)

          # Check global error rate
          error_rate = data['metrics']['http_req_failed']['values']['rate']
          assert error_rate < 0.01, f'Error rate {error_rate:.2%} >= 1%'

          # Check p95 latencies per scenario
          for scenario in ['simple_chat', 'deep_mode', 'upload_kb_search', 'upload_download', 'sse_stream', 'kb_search']:
              key = f'http_req_duration{{scenario:{scenario}}}'
              if key in data['metrics']:
                  p95 = data['metrics'][key]['values']['p(95)']
                  thresholds = {
                      'simple_chat': 3000,
                      'deep_mode': 15000,
                      'upload_kb_search': 10000,
                      'upload_download': 5000,
                      'sse_stream': 30000,
                      'kb_search': 5000,
                  }
                  threshold = thresholds[scenario]
                  assert p95 < threshold, f'{scenario} p95 {p95:.0f}ms > {threshold}ms'

          print('✅ All SLOs passed')
          "

      - name: Upload results
        uses: actions/upload-artifact@v4
        if: always()
        with:
          name: k6-results-${{ github.run_id }}
          path: |
            summary.json
            results.json
            server.log
          retention-days: 7

  # Locust alternative (Python-based)
  locust-test:
    name: Locust Test (Python)
    runs-on: ubuntu-latest
    timeout-minutes: 20
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install locust

      - name: Start Pluto server
        run: |
          nohup uvicorn backend.main:app --host 0.0.0.0 --port 8000 > server.log 2>&1 &
          sleep 10
          curl -f http://localhost:8000/api/health || (cat server.log && exit 1)

      - name: Run Locust headless
        run: |
          locust -f locustfile.py \
            --host=http://localhost:8000 \
            --headless \
            -u 30 \
            -r 5 \
            -t 2m \
            --html=locust-report.html \
            --csv=locust-report
        env:
          BASE_URL: http://localhost:8000

      - name: Check Locust SLOs
        run: |
          python -c "
          import csv
          import sys

          with open('locust-report_stats.csv') as f:
              reader = csv.DictReader(f)
              rows = list(reader)

          total_failures = sum(int(r['Failure Count']) for r in rows)
          total_requests = sum(int(r['Request Count']) for r in rows)
          error_rate = total_failures / max(1, total_requests)

          # Check p95 from aggregated stats
          for r in rows:
              if r['Name'] == 'Aggregated':
                  p95 = float(r['95%'])
                  break

          assert error_rate < 0.01, f'Error rate {error_rate:.2%} >= 1%'
          assert p95 < 5000, f'p95 {p95:.0f}ms > 5000ms'

          print(f'✅ Locust SLOs passed: error_rate={error_rate:.2%}, p95={p95:.0f}ms')
          "

      - name: Upload Locust report
        uses: actions/upload-artifact@v4
        if: always()
        with:
          name: locust-report-${{ github.run_id }}
          path: |
            locust-report.html
            locust-report_*.csv
            server.log
          retention-days: 7

  # Regression comparison (compare with baseline)
  regression-check:
    name: Performance Regression Check
    runs-on: ubuntu-latest
    needs: [load-test, locust-test]
    if: github.event_name == 'schedule' || github.ref == 'refs/heads/main'
    steps:
      - uses: actions/checkout@v4

      - name: Download baseline metrics
        uses: actions/download-artifact@v4
        with:
          name: k6-results-baseline
          path: baseline/
        continue-on-error: true

      - name: Download current metrics
        uses: actions/download-artifact@v4
        with:
          name: k6-results-${{ github.run_id }}
          path: current/

      - name: Compare metrics
        run: |
          python -c "
          import json
          import sys

          try:
              with open('baseline/summary.json') as f:
                  baseline = json.load(f)
              with open('current/summary.json') as f:
                  current = json.load(f)
          except FileNotFoundError:
              print('No baseline found, skipping regression check')
              sys.exit(0)

          # Compare p95 latencies (allow 20% regression)
          for scenario in ['simple_chat', 'deep_mode', 'upload_kb_search', 'upload_download', 'sse_stream', 'kb_search']:
              key = f'http_req_duration{{scenario:{scenario}}}'
              if key in baseline['metrics'] and key in current['metrics']:
                  b_p95 = baseline['metrics'][key]['values']['p(95)']
                  c_p95 = current['metrics'][key]['values']['p(95)']
                  regression = (c_p95 - b_p95) / b_p95
                  if regression > 0.2:
                      print(f'⚠️ REGRESSION: {scenario} p95 increased by {regression:.1%} (baseline: {b_p95:.0f}ms, current: {c_p95:.0f}ms)')
                      sys.exit(1)
                  else:
                      print(f'✅ {scenario}: {b_p95:.0f}ms → {c_p95:.0f}ms ({regression:+.1%})')

          print('✅ No significant regressions detected')
          "
```

## Running Locally

### Install k6
```bash
# macOS
brew install k6

# Windows
choco install k6

# Linux
sudo gpg -k
sudo gpg --no-default-keyring --keyring /usr/share/keyrings/k6-archive-keyring.gpg --keyserver hkp://keyserver.ubuntu:80 --recv-keys C5AD17C747E3415A3642D57D77C6C491D6AC1D69
echo "deb [signed-by=/usr/share/keyrings/k6-archive-keyring.gpg] https://dl.k6.io/deb stable main" | sudo tee /etc/apt/sources.list.d/k6.list
sudo apt-get update
sudo apt-get install k6
```

### Run Load Test
```bash
# Quick smoke test
k6 run --vus 10 --duration 30s load-test/k6-scenarios.js

# Full test (50 VUs, 5 minutes)
k6 run --vus 50 --duration 5m load-test/k6-scenarios.js

# With InfluxDB output
k6 run --vus 50 --duration 5m --out influxdb=http://localhost:8086/k6 load-test/k6-scenarios.js

# Custom base URL
BASE_URL=http://staging.pluto.app k6 run --vus 50 --duration 5m load-test/k6-scenarios.js
```

### Run Locust
```bash
# Install
pip install locust

# Run headless
locust -f locustfile.py --host=http://localhost:8000 --headless -u 50 -r 5 -t 5m

# With web UI
locust -f locustfile.py --host=http://localhost:8000
# Open http://localhost:8089
```

## SLO Targets

| Scenario | Weight | p95 Target | Error Rate |
|----------|--------|------------|------------|
| Simple Chat | 40% | < 3s | < 1% |
| Deep Mode | 15% | < 15s | < 1% |
| Upload + KB Search | 15% | < 10s | < 1% |
| Upload + Download | 10% | < 5s | < 1% |
| SSE Stream | 10% | < 30s | < 1% |
| KB Search | 10% | < 5s | < 1% |

**Global:** Error rate < 1%, p95 < 5s (weighted average)

## Monitoring Integration

### InfluxDB + Grafana
```bash
# Start InfluxDB + Grafana
docker-compose -f observability/docker-compose.observability.yml up -d

# Run k6 with InfluxDB output
k6 run --out influxdb=http://localhost:8086/k6 load-test/k6-scenarios.js
```

### Prometheus + Grafana
```bash
# Use k6 Prometheus remote write
k6 run --out prometheus-rw=http://localhost:9090/api/v1/write load-test/k6-scenarios.js
```

## Performance Budgets (for PR gates)

| Metric | Budget | Alert Threshold |
|--------|--------|-----------------|
| Global error rate | < 1% | > 1% = fail |
| p95 latency (weighted) | < 5s | > 5s = fail |
| Simple chat p95 | < 3s | > 3s = fail |
| Deep mode p95 | < 15s | > 15s = fail |
| SSE p95 | < 30s | > 30s = fail |
| Regression vs baseline | < 20% | > 20% = warn |

## Running in Staging/Production

```bash
# Staging
BASE_URL=https://staging.pluto.app k6 run --vus 20 --duration 3m load-test/k6-scenarios.js

# Production (read-only, limited)
BASE_URL=https://pluto.app k6 run --vus 5 --duration 1m --tag 'env=prod' load-test/k6-scenarios.js
```
