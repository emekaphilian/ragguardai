# Deployment

## Local

Run the pipeline directly or through Docker Compose.

## AWS direction

A target production topology is:

S3 → ingestion/processing → RAGGuard API → Bedrock + vector DB + metadata store → CloudWatch.

Terraform in this repository is a starter infrastructure layer. It should be validated and hardened before production use.
