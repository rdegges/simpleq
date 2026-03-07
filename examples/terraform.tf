terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

variable "aws_region" {
  type    = string
  default = "us-east-1"
}

resource "aws_sqs_queue" "emails_dlq" {
  name = "emails-dlq"
}

resource "aws_sqs_queue" "emails" {
  name                       = "emails"
  visibility_timeout_seconds = 300
  receive_wait_time_seconds  = 20
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.emails_dlq.arn
    maxReceiveCount     = 3
  })
}
