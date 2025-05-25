# 🛠️ New Relic Dashboard Updater

This tool automates the download, validation, and transformation of NRQL queries in New Relic dashboards using OpenTelemetry-compatible metrics.

---

## 📦 Features

- ✅ Download dashboards from multiple accounts
- 🔍 Detect and convert `FROM Span` queries to `FROM Metric`
- 🔁 Replace variables (including multi-select and NRQL-based)
- 🚀 Validate NRQL queries via New Relic GraphQL API (in batches)
- 📄 Save original and updated dashboards in JSON and CSV formats

---

## 📁 Project Structure

```
newrelic_dashboard_updater/
├── main.py                      # Entry script with --mode flags
├── config.py                   # API key and account ID config
├── graphql/                    # GraphQL queries and validators
├── utils/                      # Helpers: variable resolver, CSV, mapping
├── mappers/                   # span_to_metric_mapper.json
├── data/                      # Downloaded dashboard JSONs
├── output/                    # Validation results CSV
```

---

## 🔧 Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Set your API key and account IDs in `config.py`:
```python
API_KEY = "YOUR_NEW_RELIC_API_KEY"
ACCOUNT_IDS = [12345678, 98765432]
```

3. (Optional) Edit `mappers/span_to_metric_mapper.json` to customize metric mapping.

---

## 🚀 Usage

Run with one of the following modes:

### 📥 Download Dashboards
```bash
python main.py --mode download
```

### ✅ Validate (but don’t update) queries
```bash
python main.py --mode validate
```

### 🔄 Update queries if valid
```bash
python main.py --mode update
```

### 🎯 Single Dashboard Only
```bash
python main.py --mode validate --guid d123-abc-456
```

---

## 📊 Output
- `data/` — JSON files of dashboards
- `output/validated_results.csv` — CSV of widgets with `result` status: `failed`, `NA`, or updated query

---

## 🧪 Coming Soon
- Unit tests
- Docker deployment
- Web UI or CLI wizard

---

## 🧠 Tips
- Use the `mapper_loader.py` to expand mapping rules
- Use `logger.py` to control output levels (INFO, DEBUG, etc.)

---

## 📬 Need Help?
Continue this session by re-uploading your project and asking for improvements.
