# TheoryY Research — Python client

Official CLI + SDK for the TheoryY Research API. This package contains **no**
research logic — it only talks to a TheoryY server over HTTP, so it is the same
whether that server is our hosted SaaS or a self-hosted instance you run.

## Install

```bash
pip install theory-y          # from PyPI (hosted SaaS users)
# or, from this repo:
pip install ./client/python
```

## Configure

```bash
# Hosted SaaS: log in, token is saved for you
theory-y --url https://api.theory-y.example login

# Or save an API key / license token directly
theory-y auth --url https://api.theory-y.example --key ty_xxxx.yyyy
```

Credentials resolve from `--url/--key` flags → `THEORYY_URL`/`THEORYY_API_KEY`
env vars → `~/.theory-y/config.json`.

## Use

```bash
theory-y tickers                       # supported universe
theory-y memo PCOR --format pdf -o pcor.pdf
theory-y memo PCOR --no-wait           # submit only; poll later
theory-y status <job_id>
theory-y download <job_id> -f docx -o pcor.docx
theory-y sector PCOR APPF Z -o sheet.csv
theory-y usage                         # SaaS: plan + quota
```

### SDK

```python
from theory_y import Client

with Client(base_url="https://api.theory-y.example", api_key="ty_xxxx.yyyy") as c:
    path = c.generate("PCOR", fmt="pdf", out_path="pcor.pdf")
    print("saved", path)
```
