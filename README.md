# Ithaca Trading Demo

## Installation

Create environment

```bash
pip install -r requirements.txt
```


## Setup

1. Login to frontend


CANARY EVN: https://app.canary.ithacanoemon.tech
PRODUCTION: https://app.ithacaprotocol.io/

2. Fund account using Dashboard

3. Link an RSA KEY by going to "Account Access Management" > Regenerate API. Then either copy "private-key.pem" to pash or insert private key are a variable in the `.env` file


## Running

```
python app.py
```

This will connect to websocket and listen to new trades comming in. If the trade price crosses mid for the market maker, the script will send a trade to match
