# LocalStack

SimpleQ works well with LocalStack for local development and CI.

## Host machine

```bash
docker compose up -d localstack
export SIMPLEQ_ENDPOINT_URL=http://localhost:4566
python examples/basic.py
```

If you already standardize on AWS SDK endpoint variables, SimpleQ also honors
`AWS_ENDPOINT_URL_SQS` and `AWS_ENDPOINT_URL`.

## Dev container

The repository `docker-compose.yml` configures the app container to talk to `http://localstack:4566`.

```bash
docker compose run --rm app uv run pytest tests/integration
```

## Auto-detection

SimpleQ detects LocalStack from:

- `SIMPLEQ_ENDPOINT_URL`
- `AWS_ENDPOINT_URL_SQS`
- `AWS_ENDPOINT_URL`
- `LOCALSTACK_HOSTNAME`
- `CI`
- `SIMPLEQ_ENV=test`
- a reachable `http://localhost:4566`

That keeps local setup small without making production configuration implicit.
