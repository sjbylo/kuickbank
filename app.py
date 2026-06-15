import json
import os
import socket
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

app = Flask(__name__)
app.secret_key = os.urandom(24)

# ---------------------------------------------------------------------------
# Configuration from environment variables (same pattern as flask-vote-app)
# ---------------------------------------------------------------------------
DB_TYPE = os.environ.get('DB_TYPE', 'sqlite').lower()
ENDPOINT_ADDRESS = os.environ.get('ENDPOINT_ADDRESS', '')
PORT = os.environ.get('PORT', '5432' if DB_TYPE == 'postgresql' else '3306')
DB_NAME = os.environ.get('DB_NAME', 'quickbank')
MASTER_USERNAME = os.environ.get('MASTER_USERNAME', 'bankuser')
MASTER_PASSWORD = os.environ.get('MASTER_PASSWORD', '')

CLUSTER_NAME = os.environ.get('CLUSTER_NAME', socket.gethostname())
APP_COLOR = os.environ.get('APP_COLOR', 'blue')
RESET_INTERVAL = int(os.environ.get('RESET_INTERVAL', '600'))
RATE_LIMIT_ENABLED = os.environ.get('RATE_LIMIT_ENABLED', 'true').lower() == 'true'

MAX_TRANSACTION = 50000
SEED_BALANCE = 10000

# ---------------------------------------------------------------------------
# Database URI
# ---------------------------------------------------------------------------
if ENDPOINT_ADDRESS:
    if DB_TYPE == 'postgresql':
        db_uri = f'postgresql+pg8000://{MASTER_USERNAME}:{MASTER_PASSWORD}@{ENDPOINT_ADDRESS}:{PORT}/{DB_NAME}'
    elif DB_TYPE == 'mysql':
        db_uri = f'mysql+pymysql://{MASTER_USERNAME}:{MASTER_PASSWORD}@{ENDPOINT_ADDRESS}:{PORT}/{DB_NAME}'
    else:
        db_uri = f'sqlite:///{Path(__file__).parent / "data" / "app.db"}'
else:
    db_uri = f'sqlite:///{Path(__file__).parent / "data" / "app.db"}'
    DB_TYPE = 'sqlite'

app.config['SQLALCHEMY_DATABASE_URI'] = db_uri
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ---------------------------------------------------------------------------
# Rate limiter (toggleable at runtime)
# ---------------------------------------------------------------------------
rate_limit_enabled = RATE_LIMIT_ENABLED

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
    enabled=True,
)

TRANSACTION_LIMIT = "10/minute;1/5seconds"

# ---------------------------------------------------------------------------
# Auto-reset state
# ---------------------------------------------------------------------------
last_reset_time = time.time()
reset_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class Account(db.Model):
    __tablename__ = 'accounts'
    id = db.Column(db.Integer, primary_key=True)
    account_number = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    balance = db.Column(db.Float, nullable=False, default=0.0)
    transactions = db.relationship('Transaction', backref='account', lazy=True,
                                   order_by='Transaction.timestamp.desc()')


class Transaction(db.Model):
    __tablename__ = 'transactions'
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'), nullable=False)
    type = db.Column(db.String(20), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    description = db.Column(db.String(200), nullable=False)
    balance_after = db.Column(db.Float, nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------
def load_seed_data():
    seed_file = Path(__file__).parent / 'seeds' / 'seed_data.json'
    if seed_file.exists():
        with open(seed_file) as f:
            return json.load(f)
    return {
        "account": {"account_number": "1001-2345-6789", "name": "QuickBank Demo", "balance": SEED_BALANCE},
        "transactions": []
    }


def seed_database():
    """Seed or reset the database to initial state."""
    global last_reset_time

    db.drop_all()
    db.create_all()

    seed = load_seed_data()
    acct_data = seed['account']
    account = Account(
        account_number=acct_data['account_number'],
        name=acct_data['name'],
        balance=acct_data['balance']
    )
    db.session.add(account)
    db.session.flush()

    for tx in seed.get('transactions', []):
        t = Transaction(
            account_id=account.id,
            type=tx['type'],
            amount=tx['amount'],
            description=tx['description'],
            balance_after=tx['balance_after'],
            timestamp=datetime.fromisoformat(tx['timestamp'])
        )
        db.session.add(t)

    db.session.commit()
    last_reset_time = time.time()


# ---------------------------------------------------------------------------
# Auto-reset background thread
# ---------------------------------------------------------------------------
def auto_reset_worker():
    global last_reset_time
    while True:
        if RESET_INTERVAL <= 0:
            time.sleep(60)
            continue
        elapsed = time.time() - last_reset_time
        remaining = RESET_INTERVAL - elapsed
        if remaining <= 0:
            with reset_lock:
                with app.app_context():
                    print(f"[QuickBank] Auto-resetting account (every {RESET_INTERVAL}s)")
                    seed_database()
        else:
            time.sleep(min(remaining, 5))


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route('/')
def index():
    start = time.time()
    account = Account.query.first()
    if not account:
        seed_database()
        account = Account.query.first()

    transactions = Transaction.query.filter_by(account_id=account.id)\
        .order_by(Transaction.timestamp.desc()).limit(50).all()

    elapsed_ms = round((time.time() - start) * 1000, 1)

    reset_remaining = 0
    if RESET_INTERVAL > 0:
        reset_remaining = max(0, int(RESET_INTERVAL - (time.time() - last_reset_time)))

    return render_template('index.html',
                           account=account,
                           transactions=transactions,
                           cluster_name=CLUSTER_NAME,
                           app_color=APP_COLOR,
                           hostname=socket.gethostname(),
                           response_time=elapsed_ms,
                           rate_limit_on=rate_limit_enabled,
                           reset_remaining=reset_remaining,
                           reset_interval=RESET_INTERVAL,
                           db_type=DB_TYPE)


@app.route('/deposit', methods=['POST'])
@limiter.limit(TRANSACTION_LIMIT, exempt_when=lambda: not rate_limit_enabled)
def deposit():
    try:
        amount = float(request.form.get('amount', 0))
    except (ValueError, TypeError):
        flash('Invalid amount.', 'error')
        return redirect(url_for('index'))

    if amount <= 0:
        flash('Amount must be positive.', 'error')
        return redirect(url_for('index'))
    if amount > MAX_TRANSACTION:
        flash(f'Maximum transaction is ${MAX_TRANSACTION:,.0f}.', 'error')
        return redirect(url_for('index'))

    with reset_lock:
        account = Account.query.first()
        if not account:
            flash('No account found.', 'error')
            return redirect(url_for('index'))

        account.balance = Account.balance + amount
        db.session.flush()
        refreshed = Account.query.get(account.id)

        tx = Transaction(
            account_id=account.id,
            type='deposit',
            amount=amount,
            description=f'Deposit ${amount:,.2f}',
            balance_after=refreshed.balance,
            timestamp=datetime.now(timezone.utc)
        )
        db.session.add(tx)
        db.session.commit()

    flash(f'Deposited ${amount:,.2f}', 'success')
    return redirect(url_for('index'))


@app.route('/withdraw', methods=['POST'])
@limiter.limit(TRANSACTION_LIMIT, exempt_when=lambda: not rate_limit_enabled)
def withdraw():
    try:
        amount = float(request.form.get('amount', 0))
    except (ValueError, TypeError):
        flash('Invalid amount.', 'error')
        return redirect(url_for('index'))

    if amount <= 0:
        flash('Amount must be positive.', 'error')
        return redirect(url_for('index'))
    if amount > MAX_TRANSACTION:
        flash(f'Maximum transaction is ${MAX_TRANSACTION:,.0f}.', 'error')
        return redirect(url_for('index'))

    with reset_lock:
        account = Account.query.first()
        if not account:
            flash('No account found.', 'error')
            return redirect(url_for('index'))

        if amount > account.balance:
            flash('Insufficient funds.', 'error')
            return redirect(url_for('index'))

        account.balance = Account.balance - amount
        db.session.flush()
        refreshed = Account.query.get(account.id)

        tx = Transaction(
            account_id=account.id,
            type='withdrawal',
            amount=amount,
            description=f'Withdrawal ${amount:,.2f}',
            balance_after=refreshed.balance,
            timestamp=datetime.now(timezone.utc)
        )
        db.session.add(tx)
        db.session.commit()

    flash(f'Withdrew ${amount:,.2f}', 'success')
    return redirect(url_for('index'))


@app.route('/health')
def health():
    return jsonify({"status": "ok"}), 200


@app.route('/admin/ratelimit/on')
def ratelimit_on():
    global rate_limit_enabled
    rate_limit_enabled = True
    return jsonify({"rate_limiting": "enabled"}), 200


@app.route('/admin/ratelimit/off')
def ratelimit_off():
    global rate_limit_enabled
    rate_limit_enabled = False
    return jsonify({"rate_limiting": "disabled"}), 200


@app.route('/admin/ratelimit/status')
def ratelimit_status():
    return jsonify({
        "rate_limiting": "enabled" if rate_limit_enabled else "disabled",
        "limits": TRANSACTION_LIMIT
    }), 200


# ---------------------------------------------------------------------------
# Error handler for rate limit exceeded
# ---------------------------------------------------------------------------
@app.errorhandler(429)
def ratelimit_handler(e):
    flash('Too many requests. Please wait a few seconds.', 'error')
    return redirect(url_for('index'))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    data_dir = Path(__file__).parent / 'data'
    data_dir.mkdir(exist_ok=True)

    with app.app_context():
        print("Check if account already exists in the db")
        db.create_all()
        if not Account.query.first():
            print("Seeding database with initial data ...")
            seed_database()
        else:
            print("Account found, skipping seed")

    if RESET_INTERVAL > 0:
        reset_thread = threading.Thread(target=auto_reset_worker, daemon=True)
        reset_thread.start()
        print(f"Auto-reset enabled: every {RESET_INTERVAL} seconds")
    else:
        print("Auto-reset disabled")

    print(f"Rate limiting: {'ON' if rate_limit_enabled else 'OFF'}")
    print(f"Database: {DB_TYPE} ({'external' if ENDPOINT_ADDRESS else 'internal'})")
    print(f"Cluster: {CLUSTER_NAME} | Color: {APP_COLOR}")

    app.run(host='0.0.0.0', port=8080, debug=False)
