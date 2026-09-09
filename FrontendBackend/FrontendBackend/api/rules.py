"""
Configurable business rule engine for fraud detection.
Rules are defined as simple evaluators with priority and weight.
"""
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple
from datetime import datetime, timedelta

@dataclass
class RuleResult:
    name: str
    triggered: bool
    severity: str
    reason: str
    weight: float

class RuleEngine:
    def __init__(self, config: Dict[str, Any] | None = None):
        # Default thresholds; can be loaded from DB or settings later
        cfg = config or {}
        self.amount_high = float(cfg.get('amount_high', 1000.0))
        self.high_ratio_threshold = float(cfg.get('high_ratio_threshold', 0.1))
        self.night_hours = tuple(cfg.get('night_hours', (22, 5)))  # start, end
        self.velocity_daily_limit = int(cfg.get('velocity_daily_limit', 20))
        self.failed_txn_7d_limit = int(cfg.get('failed_txn_7d_limit', 3))
        self.young_account_days_risky = int(cfg.get('young_account_days_risky', 30))
        self.young_account_days_critical = int(cfg.get('young_account_days_critical', 7))
        self.weights = cfg.get('weights', {}) or {}
        self.rules_cap = float(cfg.get('rules_cap', 0.5))

    def evaluate(self, txn: Dict[str, Any]) -> Tuple[List[RuleResult], float]:
        results: List[RuleResult] = []

        # Safe numeric conversions
        def safe_float(v, default=0.0):
            if v is None or v == '' or v == 'None':
                return default
            try:
                return float(v)
            except (ValueError, TypeError):
                return default
        
        def safe_int(v, default=0):
            if v is None or v == '' or v == 'None':
                return default
            try:
                return int(float(v))
            except (ValueError, TypeError):
                return default
        
        amt = safe_float(self._safe_get(txn, 'transaction_amount', 0.0))
        # account_balance is optional in new UI; only use ratio rule when provided and positive
        bal_raw = self._safe_get(txn, 'account_balance', None)
        bal = safe_float(bal_raw, None) if bal_raw not in (None, '', 'None') else None
        ratio = (amt / (bal + 1.0)) if (bal is not None and bal >= 0) else None
        daily_count = safe_int(self._safe_get(txn, 'daily_transaction_count', 0))
        failed_7d = safe_int(self._safe_get(txn, 'failed_transaction_count_7d', 0))
        channel = str(self._safe_get(txn, 'channel', 'UNKNOWN')).upper()
        kyc_verified = str(self._safe_get(txn, 'kyc_verified', 'false')).lower() in ('1','true','yes')
        timestamp = self._parse_dt(self._safe_get(txn, 'timestamp'))
        account_age_days = safe_int(self._safe_get(txn, 'account_age_days', 0))

        # Rule: High amount
        results.append(RuleResult(
            name='HIGH_AMOUNT',
            triggered=amt >= self.amount_high,
            severity='HIGH' if amt >= self.amount_high * 2 else 'MEDIUM',
            reason=f'Amount {amt} exceeds threshold {self.amount_high}',
            weight=float(self.weights.get('HIGH_AMOUNT', 0.15)),
        ))

        # Rule: High amount to balance ratio
        # Apply ratio rule only when balance is provided
        if ratio is not None:
            results.append(RuleResult(
                name='HIGH_AMOUNT_BAL_RATIO',
                triggered=ratio > self.high_ratio_threshold,
                severity='HIGH' if ratio > self.high_ratio_threshold * 2 else 'MEDIUM',
                reason=f'Amount/balance ratio {ratio:.3f} > {self.high_ratio_threshold}',
                weight=float(self.weights.get('HIGH_AMOUNT_BAL_RATIO', 0.2)),
            ))
        else:
            results.append(RuleResult(
                name='HIGH_AMOUNT_BAL_RATIO',
                triggered=False,
                severity='LOW',
                reason='Balance not provided; ratio rule skipped',
                weight=0.0,
            ))

        # Rule: Night time transaction
        night = False
        if timestamp is not None:
            start, end = self.night_hours
            hour = timestamp.hour
            night = (hour >= start) or (hour <= end) if start > end else (start <= hour <= end)
        results.append(RuleResult(
            name='NIGHT_TIME',
            triggered=night,
            severity='LOW',
            reason='Transaction during night hours',
            weight=float(self.weights.get('NIGHT_TIME', 0.05)),
        ))

        # Rule: High velocity
        results.append(RuleResult(
            name='HIGH_VELOCITY',
            triggered=daily_count > self.velocity_daily_limit,
            severity='MEDIUM',
            reason=f'Daily transaction count {daily_count} > {self.velocity_daily_limit}',
            weight=float(self.weights.get('HIGH_VELOCITY', 0.10)),
        ))

        # Rule: Recent failed transactions
        results.append(RuleResult(
            name='RECENT_FAILURES',
            triggered=failed_7d > self.failed_txn_7d_limit,
            severity='MEDIUM',
            reason=f'{failed_7d} failed txns in 7d > {self.failed_txn_7d_limit}',
            weight=float(self.weights.get('RECENT_FAILURES', 0.10)),
        ))

        # Rule: Unverified KYC for risky channels
        risky_channels = {'ONLINE', 'THIRD_PARTY', 'P2P'}
        results.append(RuleResult(
            name='UNVERIFIED_KYC_RISKY_CHANNEL',
            triggered=(not kyc_verified) and (channel in risky_channels),
            severity='HIGH',
            reason=f'Unverified KYC on risky channel {channel}',
            weight=float(self.weights.get('UNVERIFIED_KYC_RISKY_CHANNEL', 0.20)),
        ))

        # Rule: Very young account age increases risk (policy driven)
        if account_age_days > 0:
            results.append(RuleResult(
                name='YOUNG_ACCOUNT_AGE',
                triggered=account_age_days < self.young_account_days_risky,
                severity='HIGH' if account_age_days < self.young_account_days_critical else 'MEDIUM',
                reason=f'Account age {account_age_days} days < {self.young_account_days_risky} days',
                weight=float(self.weights.get('YOUNG_ACCOUNT_AGE', 0.12)),
            ))
        else:
            results.append(RuleResult(
                name='YOUNG_ACCOUNT_AGE',
                triggered=False,
                severity='LOW',
                reason='Account age not provided or invalid',
                weight=0.0,
            ))

        # Combine into risk adjustment (0..1)
        adjustment = 0.0
        for r in results:
            if r.triggered:
                adjustment += r.weight
        adjustment = min(self.rules_cap, adjustment)  # cap adjustment per policy

        return results, adjustment

    def _safe_get(self, d: Dict[str, Any], key: str, default: Any = None) -> Any:
        try:
            return d.get(key, default)
        except Exception:
            return default

    def _parse_dt(self, v: Any):
        if not v:
            return None
        try:
            if isinstance(v, datetime):
                return v
            from dateutil.parser import isoparse
            return isoparse(str(v))
        except Exception:
            return None
