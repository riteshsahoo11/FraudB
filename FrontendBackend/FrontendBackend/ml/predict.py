"""
Prediction helpers and demo data generator
"""
from __future__ import annotations
import random
import csv
import io
from datetime import datetime, timedelta
from typing import List, Dict, Any

from .models import predict_transaction, predict_transactions_batch, initialize_predictor

# Minimal required input fields for real-time prediction across the app
REQUIRED_INPUT_FIELDS = [
    'customer_id',
    'account_age_days',
    'transaction_amount',
    'channel',
    'kyc_verified',
    'timestamp',
]

OPTIONAL_FIELDS = [
    'account_balance',              # Enables amount/balance ratio rule
    'daily_transaction_count',
    'failed_transaction_count_7d',
]

CHANNELS = ['ONLINE', 'BRANCH', 'ATM', 'P2P', 'THIRD_PARTY']


def _random_bool(p_true: float = 0.5) -> bool:
    return random.random() < p_true


def generate_demo_samples(n: int = 20, seed: int | None = None) -> List[Dict[str, Any]]:
    """Generate n realistic demo transactions matching the app's expected schema."""
    if seed is not None:
        random.seed(seed)
    now = datetime.utcnow()
    samples: List[Dict[str, Any]] = []

    for i in range(n):
        amt_base = random.choice([25, 49, 99, 149, 199, 499, 749, 999, 1500, 2500, 5000])
        # introduce some variability
        transaction_amount = round(amt_base * (0.7 + random.random()*0.8), 2)
        account_age_days = random.randint(5, 2000)
        channel = random.choice(CHANNELS)
        kyc_verified = _random_bool(0.8)
        # randomize timestamp in last 14 days
        ts = now - timedelta(days=random.randint(0, 14), hours=random.randint(0, 23), minutes=random.randint(0, 59))

        row: Dict[str, Any] = {
            'customer_id': f'CUST{100000 + i}',
            'account_age_days': account_age_days,
            'transaction_amount': transaction_amount,
            'channel': channel,
            'kyc_verified': str(kyc_verified).lower(),  # backend handles common truthy strings
            'timestamp': ts.isoformat() + 'Z',
        }

        # optional fields (probabilistically include)
        if _random_bool(0.6):
            # Make balance sometimes low to trigger rules
            balance = round(transaction_amount * random.choice([0.1, 0.5, 1.5, 3.0, 10.0]) + random.random()*50, 2)
            row['account_balance'] = balance
        if _random_bool(0.4):
            row['daily_transaction_count'] = random.randint(0, 30)
        if _random_bool(0.3):
            row['failed_transaction_count_7d'] = random.randint(0, 5)

        samples.append(row)

    return samples


def generate_demo_csv(n: int = 50, seed: int | None = 42) -> str:
    """Generate a CSV string of demo transactions."""
    rows = generate_demo_samples(n=n, seed=seed)
    # union headers across rows
    headers = list({k for r in rows for k in r.keys()})
    # ensure required fields first
    ordered = [*REQUIRED_INPUT_FIELDS, *[h for h in headers if h not in REQUIRED_INPUT_FIELDS]]

    s = io.StringIO()
    w = csv.DictWriter(s, fieldnames=ordered)
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return s.getvalue()


def predict_demo(n: int = 20) -> List[Dict[str, Any]]:
    """Run predictions on generated demo samples using the initialized model."""
    initialize_predictor()
    data = generate_demo_samples(n=n)
    return predict_transactions_batch(data)
