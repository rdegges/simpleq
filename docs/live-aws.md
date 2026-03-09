# Live AWS Testing

SimpleQ ships with an optional live AWS smoke suite in `tests/live/`.

## Credentials

Create a least-privilege IAM user or role for the smoke suite and store the credentials in a local `.env` file:

```bash
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_DEFAULT_REGION=us-east-1
```

The repository ignores `.env`, and the test suite never creates credentials automatically.

## IAM policy

Use `tests/live/iam-policy.json` as the baseline policy document.
The smoke suite now reconciles queue tags as part of queue setup, so the IAM
principal also needs `sqs:ListQueueTags`, `sqs:TagQueue`, and
`sqs:UntagQueue`.

## Running the live suite

```bash
docker compose run --rm app uv run pytest tests/live --run-live-aws -m live
```
