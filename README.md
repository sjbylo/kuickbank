# kuickbank

A sample FSI (Financial Services Industry) banking demo application written in Python (Flask).

Users are presented with a shared bank account dashboard. They can make deposits and withdrawals using pre-set quick buttons or custom amounts, and see all transactions in a live ledger. Account data is stored in an internal SQLite database. As an alternative, the application can use an external PostgreSQL or MySQL database for shared state across multiple instances.

The repo has been designed to make it easy to build and run on OpenShift.

This application is intended for demo use only.

[![Docker Repository on Quay](https://quay.io/repository/sjbylo/kuickbank/status "Docker Repository on Quay")](https://quay.io/repository/sjbylo/kuickbank)

## Local deployment

This application can be deployed locally. Install git and clone the repository:

```
git clone https://github.com/sjbylo/kuickbank
cd kuickbank
```

Install the dependencies:

```
pip install flask
pip install flask-sqlalchemy
pip install flask-limiter
pip install pg8000
pip install PyMySQL
```

or install from the requirements file:

```
pip install -r requirements.txt
```

and start the application:

```
python app.py
Check if account already exists in the db
Seeding database with initial data ...
Auto-reset enabled: every 600 seconds
Rate limiting: ON
Database: sqlite (internal)
Cluster: my-laptop | Color: blue
 * Running on http://0.0.0.0:8080/ (Press CTRL+C to quit)
```

View the app in the browser at http://localhost:8080/. The test script can also be used to test the app:

```
./test-kuickbank.sh http://localhost:8080
```

The initial account and transactions are loaded from a JSON file called ``seed_data.json`` under the ``./seeds`` directory.
Change this file before starting the application to customize the starting balance and transactions.

The SQLite DB data file is called ``app.db`` and is located under the ``./data`` directory.
To use an external PostgreSQL database, set the environment variables by editing the ``flask.rc`` file under the application directory.

```
nano flask.rc
export PS1='[\u(kuickbank)]\> '
export ENDPOINT_ADDRESS=db
export PORT=5432
export DB_NAME=kuickbank
export MASTER_USERNAME=bankuser
export MASTER_PASSWORD=password
export DB_TYPE=postgresql
```

Make sure an external PostgreSQL database server is running according to the parameters above.

Source the file and restart the application:

```
source flask.rc
python app.py
```

Cleanup:

```
rm -f data/app.db    # optionally remove the database
```

## Docker/Podman deployment

The app can be run by pulling the image from quay.io:

```
podman run -d --rm -p 8080:8080 --name=kuickbank quay.io/sjbylo/kuickbank
curl http://localhost:8080/
```

Stop the container:

```
podman stop kuickbank
```

## Docker/Podman build and deployment

A Dockerfile is provided in the repository to build a container image.

Clone the repository:

```
git clone https://github.com/sjbylo/kuickbank
cd kuickbank
```

Build the image:

```
podman build -t kuickbank:latest .
podman images
```

Start the container:

```
podman run -d -p 8080:8080 --name=kuickbank kuickbank:latest
```

The seed data directory can be mounted as an external volume:

```
cp seeds/seed_data.json /tmp/
podman run -d -p 8080:8080 -v /tmp:/app/seeds:Z --name=kuickbank kuickbank:latest
```

An external PostgreSQL database can be used instead of the internal SQLite by setting env variables:

```
podman run -e ENDPOINT_ADDRESS=db \
           -e PORT=5432 \
           -e DB_NAME=kuickbank \
           -e MASTER_USERNAME=bankuser \
           -e MASTER_PASSWORD=password \
           -e DB_TYPE=postgresql \
           -d -p 8080:8080 --name=kuickbank kuickbank:latest
```

Cleanup:

```
podman stop kuickbank && podman rm kuickbank
```

## Install the app onto OpenShift

Build and launch the app:

```
oc new-app python~https://github.com/sjbylo/kuickbank.git --name kuickbank
```

As an alternative to the above build, pull the latest image from quay.io registry:

```
oc new-app --docker-image=quay.io/sjbylo/kuickbank:latest --name kuickbank
```

Expose the app to the external network:

```
oc expose svc kuickbank
```

Start a database (optional, if shared state across pods is required):

```
oc new-app --name db postgresql:15 \
  -e POSTGRESQL_USER=bankuser \
  -e POSTGRESQL_PASSWORD=password \
  -e POSTGRESQL_DATABASE=kuickbank
```

Connect the app to the DB:

```
oc set env deploy kuickbank \
   ENDPOINT_ADDRESS=db \
   PORT=5432 \
   DB_NAME=kuickbank \
   MASTER_USERNAME=bankuser \
   MASTER_PASSWORD=password \
   DB_TYPE=postgresql
```

## Develop and quickly build and test the app from your local directory

To easily develop this application, we can make changes to the local files and then re-build the app by uploading the changes to a new build pod.

To do this we create a 'binary' build. Binary is referring to the way the local directory is sent or "streamed" to the build pod using tar.

```
oc new-build python --name kuickbank --binary
```

Start the build. This will upload the app code from the current working dir:

```
oc start-build kuickbank --from-dir=. --follow
```

Wait for the build to complete. Launch the app:

```
oc new-app kuickbank
```

Expose the app to the external network:

```
oc expose svc kuickbank
```

Test the app:

```
QUICKBANK_URL=$(oc get route kuickbank --template='{{.spec.host}}')
./test-kuickbank.sh http://$QUICKBANK_URL
open http://$QUICKBANK_URL/
```

Now, make changes to the local file(s) and re-build the app.
To re-build the app on the server, run the above ``oc start-build`` command again.

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `ENDPOINT_ADDRESS` | _(empty = SQLite)_ | Database host address |
| `PORT` | `5432` (pg) / `3306` (mysql) | Database port |
| `DB_NAME` | `kuickbank` | Database name |
| `MASTER_USERNAME` | `bankuser` | Database username |
| `MASTER_PASSWORD` | _(empty)_ | Database password |
| `DB_TYPE` | `sqlite` | `sqlite`, `postgresql`, or `mysql` |
| `CLUSTER_NAME` | _(hostname)_ | Displayed in UI header badge |
| `APP_COLOR` | `blue` | Header badge color (e.g. `blue`, `green`, `red`) |
| `RESET_INTERVAL` | `600` | Auto-reset interval in seconds (`0` to disable) |
| `RATE_LIMIT_ENABLED` | `true` | Enable built-in rate limiting on startup |

## Seed data

The initial account and sample transactions are loaded from ``seeds/seed_data.json``. Edit this file to change the starting balance, account name, or pre-loaded transactions.

The format is:

```json
{
  "account": {
    "account_number": "1001-2345-6789",
    "name": "KuickBank Demo",
    "balance": 10000.00
  },
  "transactions": [
    {
      "type": "deposit",
      "amount": 10000.00,
      "description": "Initial deposit",
      "balance_after": 10000.00,
      "timestamp": "2026-01-15T09:00:00"
    }
  ]
}
```

## Rate limiting

Built-in rate limiting prevents click-spam. It defaults to ON and allows a maximum of 1 transaction every 5 seconds and 10 transactions per minute per IP address.

Toggle rate limiting at runtime:

```
curl http://localhost:8080/admin/ratelimit/off     # disable
curl http://localhost:8080/admin/ratelimit/on      # enable
curl http://localhost:8080/admin/ratelimit/status  # check status
```

The current rate limiting state is also shown in the page footer.

## Auto-reset

The account balance resets to its seed value (default $10,000) and transactions are cleared automatically every 10 minutes. A countdown timer is shown in the page footer.

To change the interval, set the ``RESET_INTERVAL`` environment variable (in seconds). Set to ``0`` to disable auto-reset.

```
RESET_INTERVAL=300 python app.py    # reset every 5 minutes
RESET_INTERVAL=0 python app.py      # no auto-reset
```
